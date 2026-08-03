package api

import (
	"bytes"
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/http"
	"net/netip"
	"strconv"
	"sync"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
	"github.com/ikseth/ha-addons/ha4win/internal/registry"
)

const (
	maxRequestBody = 64 * 1024
	maxConcurrent  = 16
)

type AuditLogger interface {
	Info(string)
	Warning(string)
	Error(string)
	AuditRejection(peer, path, reason string)
	AuditActuator(peer, actuator, action string, params map[string]any)
}

type Options struct {
	Config   config.Config
	Logger   AuditLogger
	Registry *registry.Registry
}

type StartErrorKind int

const (
	StartOther StartErrorKind = iota
	StartTLS
	StartListen
)

type StartError struct {
	Kind StartErrorKind
	Err  error
}

func (e *StartError) Error() string { return e.Err.Error() }
func (e *StartError) Unwrap() error { return e.Err }

type Server struct {
	cfg      config.Config
	logger   AuditLogger
	allowed  []netip.Prefix
	http     *http.Server
	listener net.Listener
	sem      chan struct{}
	done     chan error
	stopOnce sync.Once
	registry *registry.Registry
}

func New(options Options) (*Server, error) {
	allowed, err := ParseAllowedClients(options.Config.API.AllowedClients)
	if err != nil {
		return nil, err
	}
	modules := options.Registry
	if modules == nil {
		modules = registry.Load(options.Config, options.Logger)
	}
	server := &Server{
		cfg:      options.Config,
		logger:   options.Logger,
		allowed:  allowed,
		sem:      make(chan struct{}, maxConcurrent),
		done:     make(chan error, 1),
		registry: modules,
	}
	server.http = &http.Server{
		Addr:              net.JoinHostPort(options.Config.API.BindHost, strconv.Itoa(options.Config.API.BindPort)),
		Handler:           http.HandlerFunc(server.dispatch),
		ReadTimeout:       15 * time.Second,
		ReadHeaderTimeout: 15 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
		MaxHeaderBytes:    1 << 20,
	}
	return server, nil
}

func (s *Server) Start() error {
	listener, err := net.Listen("tcp", s.http.Addr)
	if err != nil {
		return &StartError{Kind: StartListen, Err: fmt.Errorf("listen on %s: %w", s.http.Addr, err)}
	}
	if s.cfg.TLS.Enabled {
		certificate, err := tls.LoadX509KeyPair(s.cfg.TLS.CertFile, s.cfg.TLS.KeyFile)
		if err != nil {
			_ = listener.Close()
			return &StartError{Kind: StartTLS, Err: fmt.Errorf("load TLS certificate: %w", err)}
		}
		tlsConfig := &tls.Config{Certificates: []tls.Certificate{certificate}, MinVersion: tls.VersionTLS12}
		listener = tls.NewListener(listener, tlsConfig)
	}
	s.listener = listener
	go func() {
		err := s.http.Serve(listener)
		if errors.Is(err, http.ErrServerClosed) {
			err = nil
		}
		s.done <- err
		close(s.done)
	}()
	return nil
}

func (s *Server) Wait() error {
	return <-s.done
}

func (s *Server) Shutdown(ctx context.Context) error {
	var err error
	s.stopOnce.Do(func() { err = s.http.Shutdown(ctx) })
	return err
}

func (s *Server) dispatch(w http.ResponseWriter, r *http.Request) {
	defer func() {
		if recovered := recover(); recovered != nil {
			if s.logger != nil {
				s.logger.Error(fmt.Sprintf("unhandled API panic: %v", recovered))
			}
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
	}()
	timer := time.NewTimer(2 * time.Second)
	defer timer.Stop()
	select {
	case s.sem <- struct{}{}:
		defer func() { <-s.sem }()
	case <-timer.C:
		writeError(w, http.StatusServiceUnavailable, "server is busy")
		return
	case <-r.Context().Done():
		return
	}

	if !s.readBoundedBody(w, r) {
		return
	}
	if r.Method == http.MethodPost && r.ContentLength > 0 {
		mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
		if err != nil || mediaType != "application/json" {
			writeError(w, http.StatusBadRequest, "Content-Type must be application/json")
			return
		}
	}
	route, found := s.resolveRoute(r.URL.Path)
	if !found {
		writeError(w, http.StatusNotFound, "route not found")
		return
	}
	if r.Method != route.method {
		w.Header().Set("Allow", route.method)
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	if route.private {
		if !PeerAllowed(r.RemoteAddr, s.allowed) {
			s.audit(r, "client is outside api.allowed_clients")
			writeError(w, http.StatusForbidden, "client address is not allowed")
			return
		}
		token, ok := bearerToken(r.Header.Get("Authorization"))
		if !ok || !TokenMatches(s.cfg.API.Token, token) {
			s.audit(r, "missing or invalid bearer token")
			writeError(w, http.StatusUnauthorized, "missing or invalid bearer token")
			return
		}
	}
	route.handler(w, r)
}

func (s *Server) readBoundedBody(w http.ResponseWriter, r *http.Request) bool {
	if r.Body == nil || r.Body == http.NoBody {
		return true
	}
	if r.ContentLength > maxRequestBody {
		writeError(w, http.StatusRequestEntityTooLarge, "request body exceeds 64 KiB")
		return false
	}
	data, err := io.ReadAll(io.LimitReader(r.Body, maxRequestBody+1))
	_ = r.Body.Close()
	if err != nil {
		writeError(w, http.StatusBadRequest, "could not read request body")
		return false
	}
	if len(data) > maxRequestBody {
		writeError(w, http.StatusRequestEntityTooLarge, "request body exceeds 64 KiB")
		return false
	}
	r.Body = io.NopCloser(bytes.NewReader(data))
	r.ContentLength = int64(len(data))
	return true
}

func (s *Server) audit(r *http.Request, reason string) {
	if s.logger != nil {
		s.logger.AuditRejection(r.RemoteAddr, r.URL.Path, reason)
	}
}
