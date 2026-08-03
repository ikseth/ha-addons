package cpu

import (
	"testing"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type fakeSource struct {
	samples []winapi.CPUTimes
	index   int
}

func (f *fakeSource) SystemTimes() (winapi.CPUTimes, error) {
	sample := f.samples[f.index]
	if f.index < len(f.samples)-1 {
		f.index++
	}
	return sample, nil
}
func (*fakeSource) ProcessorTimes() ([]winapi.CPUTimes, error) { return nil, nil }
func (*fakeSource) Performance() (winapi.CPUPerformance, error) {
	return winapi.CPUPerformance{}, nil
}

func TestFirstCPUValueUsesInitialSample(t *testing.T) {
	source := &fakeSource{samples: []winapi.CPUTimes{{Idle: 100, Kernel: 300, User: 100}, {Idle: 120, Kernel: 360, User: 140}}}
	sensor := New(false, source)
	base := time.Unix(100, 0)
	sensor.previousAt = base
	sensor.now = func() time.Time { return base.Add(2 * time.Second) }
	data, err := sensor.Collect(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	if data["usage_percent"] != 80.0 || data["usage_user_percent"] != 40.0 || data["usage_kernel_percent"] != 40.0 {
		t.Fatalf("unexpected CPU percentages: %#v", data)
	}
}

func TestCPUWithoutPreviousSampleStartsAtZero(t *testing.T) {
	source := &fakeSource{samples: []winapi.CPUTimes{{Idle: 10, Kernel: 20, User: 10}}}
	sensor := &Sensor{source: source, now: time.Now}
	data, err := sensor.Collect(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	if data["usage_percent"] != 0.0 || data["window_seconds"] != 0.0 {
		t.Fatalf("first sample was not zero: %#v", data)
	}
}
