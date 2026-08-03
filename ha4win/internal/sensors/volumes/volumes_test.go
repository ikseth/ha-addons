package volumes

import (
	"context"
	"testing"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type fakeSource struct {
	drives  []winapi.LogicalDrive
	queried []string
}

func (f *fakeSource) LogicalDrives() ([]winapi.LogicalDrive, error) { return f.drives, nil }
func (f *fakeSource) Volume(root string) (winapi.VolumeInformation, error) {
	f.queried = append(f.queried, root)
	return winapi.VolumeInformation{TotalBytes: 100, FreeBytes: 25}, nil
}

func TestDriveTypeFilterRunsBeforeVolumeQuery(t *testing.T) {
	source := &fakeSource{drives: []winapi.LogicalDrive{{Root: `C:\`, Type: "fixed"}, {Root: `Z:\`, Type: "network"}}}
	sensor := New([]string{"fixed"}, nil, source)
	data, err := sensor.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(source.queried) != 1 || source.queried[0] != `C:\` {
		t.Fatalf("unexpected queried drives: %v", source.queried)
	}
	if data["volumes_total"] != 1 {
		t.Fatalf("unexpected payload: %#v", data)
	}
}
