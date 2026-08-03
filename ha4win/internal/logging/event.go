package logging

type eventWriter interface {
	Write(level, message string) error
	Close() error
}
