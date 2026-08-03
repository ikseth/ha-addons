package update

import (
	"fmt"
	"strconv"
	"strings"
)

type semanticVersion struct {
	major, minor, patch uint64
	prerelease          []string
}

func parseSemanticVersion(raw string) (semanticVersion, error) {
	value := strings.TrimSpace(raw)
	if strings.HasPrefix(value, "v") {
		value = value[1:]
	}
	if build := strings.IndexByte(value, '+'); build >= 0 {
		value = value[:build]
	}
	var prerelease []string
	if separator := strings.IndexByte(value, '-'); separator >= 0 {
		prerelease = strings.Split(value[separator+1:], ".")
		value = value[:separator]
		if len(prerelease) == 0 {
			return semanticVersion{}, fmt.Errorf("invalid semantic version %q", raw)
		}
		for _, identifier := range prerelease {
			if identifier == "" || !validIdentifier(identifier) {
				return semanticVersion{}, fmt.Errorf("invalid semantic version %q", raw)
			}
		}
	}
	parts := strings.Split(value, ".")
	if len(parts) != 3 {
		return semanticVersion{}, fmt.Errorf("invalid semantic version %q", raw)
	}
	numbers := make([]uint64, 3)
	for index, part := range parts {
		if part == "" || (len(part) > 1 && part[0] == '0') {
			return semanticVersion{}, fmt.Errorf("invalid semantic version %q", raw)
		}
		number, err := strconv.ParseUint(part, 10, 64)
		if err != nil {
			return semanticVersion{}, fmt.Errorf("invalid semantic version %q", raw)
		}
		numbers[index] = number
	}
	return semanticVersion{major: numbers[0], minor: numbers[1], patch: numbers[2], prerelease: prerelease}, nil
}

func validIdentifier(value string) bool {
	for _, character := range value {
		if (character < '0' || character > '9') && (character < 'A' || character > 'Z') && (character < 'a' || character > 'z') && character != '-' {
			return false
		}
	}
	return true
}

func CompareVersions(left, right string) (int, error) {
	a, err := parseSemanticVersion(left)
	if err != nil {
		return 0, err
	}
	b, err := parseSemanticVersion(right)
	if err != nil {
		return 0, err
	}
	for _, pair := range [][2]uint64{{a.major, b.major}, {a.minor, b.minor}, {a.patch, b.patch}} {
		if pair[0] < pair[1] {
			return -1, nil
		}
		if pair[0] > pair[1] {
			return 1, nil
		}
	}
	if len(a.prerelease) == 0 && len(b.prerelease) == 0 {
		return 0, nil
	}
	if len(a.prerelease) == 0 {
		return 1, nil
	}
	if len(b.prerelease) == 0 {
		return -1, nil
	}
	for index := 0; index < len(a.prerelease) && index < len(b.prerelease); index++ {
		leftID, rightID := a.prerelease[index], b.prerelease[index]
		leftNumber, leftErr := strconv.ParseUint(leftID, 10, 64)
		rightNumber, rightErr := strconv.ParseUint(rightID, 10, 64)
		switch {
		case leftErr == nil && rightErr == nil:
			if leftNumber < rightNumber {
				return -1, nil
			}
			if leftNumber > rightNumber {
				return 1, nil
			}
		case leftErr == nil:
			return -1, nil
		case rightErr == nil:
			return 1, nil
		default:
			if leftID < rightID {
				return -1, nil
			}
			if leftID > rightID {
				return 1, nil
			}
		}
	}
	if len(a.prerelease) < len(b.prerelease) {
		return -1, nil
	}
	if len(a.prerelease) > len(b.prerelease) {
		return 1, nil
	}
	return 0, nil
}
