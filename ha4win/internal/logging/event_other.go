//go:build !windows

package logging

type discardEventWriter struct{}

func openEventWriter() (eventWriter, error)           { return discardEventWriter{}, nil }
func (discardEventWriter) Write(string, string) error { return nil }
func (discardEventWriter) Close() error               { return nil }
