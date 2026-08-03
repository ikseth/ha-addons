//go:build windows

package logging

import "golang.org/x/sys/windows/svc/eventlog"

type windowsEventWriter struct {
	log *eventlog.Log
}

func openEventWriter() (eventWriter, error) {
	log, err := eventlog.Open("HA4Win")
	if err != nil {
		return nil, err
	}
	return &windowsEventWriter{log: log}, nil
}

func (w *windowsEventWriter) Write(level, message string) error {
	switch level {
	case "ERROR":
		return w.log.Error(1, message)
	case "WARNING":
		return w.log.Warning(1, message)
	default:
		return w.log.Info(1, message)
	}
}

func (w *windowsEventWriter) Close() error { return w.log.Close() }
