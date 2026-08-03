package logging

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const DefaultLogPath = `C:\ProgramData\HA4Win\logs\ha4win.log`

type Options struct {
	Path            string
	Level           string
	FileEnabled     bool
	MaxSizeMB       int
	MaxFiles        int
	EventLogEnabled bool
	Console         bool
}

type Logger struct {
	mu          sync.Mutex
	options     Options
	file        *os.File
	console     *log.Logger
	event       eventWriter
	auditByPeer map[string]time.Time
}

func New(options Options) (*Logger, error) {
	if options.Path == "" {
		options.Path = DefaultLogPath
	}
	logger := &Logger{options: options, auditByPeer: make(map[string]time.Time)}
	if options.Console {
		logger.console = log.New(os.Stderr, "", 0)
	}
	if options.FileEnabled {
		if err := os.MkdirAll(filepath.Dir(options.Path), 0o700); err != nil {
			return nil, fmt.Errorf("create log directory: %w", err)
		}
		file, err := os.OpenFile(options.Path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
		if err != nil {
			return nil, fmt.Errorf("open log file: %w", err)
		}
		logger.file = file
	}
	if options.EventLogEnabled {
		event, err := openEventWriter()
		if err != nil {
			logger.writeConsole("WARNING", "could not open Windows Event Log: "+err.Error())
		} else {
			logger.event = event
		}
	}
	return logger, nil
}

func (l *Logger) Close() error {
	l.mu.Lock()
	defer l.mu.Unlock()
	var first error
	if l.file != nil {
		first = l.file.Close()
		l.file = nil
	}
	if l.event != nil {
		if err := l.event.Close(); first == nil {
			first = err
		}
		l.event = nil
	}
	return first
}

func (l *Logger) Info(message string)    { l.write("INFO", message) }
func (l *Logger) Warning(message string) { l.write("WARNING", message) }
func (l *Logger) Error(message string)   { l.write("ERROR", message) }

func (l *Logger) AuditRejection(peer, path, reason string) {
	peerKey := peer
	if host, _, err := net.SplitHostPort(peer); err == nil {
		peerKey = host
	}
	l.mu.Lock()
	last := l.auditByPeer[peerKey]
	if time.Since(last) < 10*time.Second {
		l.mu.Unlock()
		return
	}
	l.auditByPeer[peerKey] = time.Now()
	l.mu.Unlock()
	l.Warning(fmt.Sprintf("request rejected: peer=%s path=%s reason=%s", peer, path, reason))
}

func (l *Logger) AuditActuator(peer, actuator, action string, params map[string]any) {
	encoded, err := json.Marshal(params)
	if err != nil {
		encoded = []byte(`{"unavailable":true}`)
	}
	l.writeMessage("INFO", fmt.Sprintf(
		"actuator action requested: peer=%s actuator=%s action=%s params=%s",
		peer, actuator, action, encoded,
	), true)
}

func (l *Logger) write(level, message string) {
	l.writeMessage(level, message, false)
}

func (l *Logger) writeMessage(level, message string, force bool) {
	if !force && !enabled(l.options.Level, level) {
		return
	}
	line := fmt.Sprintf("%s %-7s %s\n", time.Now().UTC().Format(time.RFC3339), level, sanitize(message))
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.console != nil {
		l.console.Print(strings.TrimSuffix(line, "\n"))
	}
	if l.file != nil {
		if err := l.rotateIfNeeded(int64(len(line))); err != nil {
			l.writeConsole("WARNING", "log rotation failed: "+err.Error())
		}
		_, _ = io.WriteString(l.file, line)
	}
	if l.event != nil {
		_ = l.event.Write(level, sanitize(message))
	}
}

func (l *Logger) rotateIfNeeded(incoming int64) error {
	if l.file == nil || l.options.MaxSizeMB <= 0 {
		return nil
	}
	info, err := l.file.Stat()
	if err != nil || info.Size()+incoming <= int64(l.options.MaxSizeMB)*1024*1024 {
		return err
	}
	if err := l.file.Close(); err != nil {
		return err
	}
	l.file = nil
	for generation := l.options.MaxFiles - 1; generation >= 1; generation-- {
		source := fmt.Sprintf("%s.%d", l.options.Path, generation)
		target := fmt.Sprintf("%s.%d", l.options.Path, generation+1)
		_ = os.Remove(target)
		if err := os.Rename(source, target); err != nil && !os.IsNotExist(err) {
			return err
		}
	}
	target := l.options.Path + ".1"
	_ = os.Remove(target)
	if err := os.Rename(l.options.Path, target); err != nil && !os.IsNotExist(err) {
		return err
	}
	file, err := os.OpenFile(l.options.Path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	l.file = file
	return nil
}

func (l *Logger) writeConsole(level, message string) {
	if l.console != nil {
		l.console.Printf("%s %-7s %s", time.Now().UTC().Format(time.RFC3339), level, sanitize(message))
	}
}

func sanitize(message string) string {
	return strings.NewReplacer("\r", " ", "\n", " ").Replace(message)
}

func enabled(configured, message string) bool {
	levels := map[string]int{"debug": 0, "info": 1, "warning": 2, "error": 3}
	messageLevel := map[string]int{"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}
	threshold, ok := levels[strings.ToLower(configured)]
	if !ok {
		threshold = 1
	}
	return messageLevel[message] >= threshold
}
