package pii

import (
	"bufio"
	"os"
	"reflect"
	"strconv"
	"strings"
	"testing"
)

// Go hard-codes what Python reads from spec/entities.yaml (entity order, default
// policies, keyword gates). These tests read the spec with a line scanner (the
// module has no YAML dependency) and fail on any drift.

type specEntity struct {
	name     string
	policy   string
	keywords []string
	window   int
}

func loadSpecEntities(t *testing.T) []specEntity {
	t.Helper()

	fh, err := os.Open("src/pii/entities.yaml")
	if err != nil {
		t.Fatalf("open spec: %v", err)
	}
	defer fh.Close()

	var (
		out        []specEntity
		inEntities bool
		inKeywords bool
	)

	sc := bufio.NewScanner(fh)
	for sc.Scan() {
		line := sc.Text()

		switch {
		case line == "entities:":
			inEntities = true

			continue
		case !strings.HasPrefix(line, " ") && strings.HasSuffix(line, ":"):
			inEntities = false
		}

		if !inEntities {
			continue
		}

		cur := len(out) - 1

		switch {
		case strings.HasPrefix(line, "  - name: "):
			out = append(out, specEntity{name: strings.TrimPrefix(line, "  - name: ")})
			inKeywords = false
		case strings.HasPrefix(line, "    default_policy: "):
			out[cur].policy = strings.TrimSpace(strings.TrimPrefix(line, "    default_policy: "))
			inKeywords = false
		case strings.HasPrefix(line, "    context_window: "):
			out[cur].window, err = strconv.Atoi(strings.TrimSpace(strings.TrimPrefix(line, "    context_window: ")))
			if err != nil {
				t.Fatalf("context_window: %v", err)
			}

			inKeywords = false
		case line == "    context_keywords:":
			inKeywords = true
		case inKeywords && strings.HasPrefix(line, "      - "):
			kw := strings.TrimPrefix(line, "      - ")
			kw = strings.Trim(kw, `"`)
			out[cur].keywords = append(out[cur].keywords, kw)
		case strings.HasPrefix(line, "    ") && !strings.HasPrefix(line, "      "):
			inKeywords = false
		}
	}

	if err := sc.Err(); err != nil {
		t.Fatalf("scan spec: %v", err)
	}

	if len(out) == 0 {
		t.Fatal("no entities parsed from the spec")
	}

	return out
}

func TestDefaultAnalyzerFollowsSpecOrder(t *testing.T) {
	var want, got []string
	for _, e := range loadSpecEntities(t) {
		want = append(want, e.name)
	}

	for _, d := range DefaultAnalyzer().detectors {
		got = append(got, string(d.Entity()))
	}

	if !reflect.DeepEqual(got, want) {
		t.Errorf("DefaultAnalyzer order\n got  %v\n want %v (spec order)", got, want)
	}
}

func TestSpecPolicyMatchesSpec(t *testing.T) {
	pol := SpecPolicy()

	for _, e := range loadSpecEntities(t) {
		if got := string(pol.action(Entity(e.name))); got != e.policy {
			t.Errorf("SpecPolicy()[%s] = %s, spec says %s", e.name, got, e.policy)
		}
	}

	if len(pol.ByEntity) != len(loadSpecEntities(t)) {
		t.Errorf("SpecPolicy lists %d entities, spec has %d", len(pol.ByEntity), len(loadSpecEntities(t)))
	}
}

func TestContextGatesMatchSpec(t *testing.T) {
	gates := map[string]contextDetector{}

	for _, d := range DefaultAnalyzer().detectors {
		if c, ok := d.(contextDetector); ok {
			gates[string(c.Entity())] = c
		}
	}

	for _, e := range loadSpecEntities(t) {
		c, gated := gates[e.name]
		if gated != (len(e.keywords) > 0) {
			t.Errorf("%s: Go gated=%v, spec keywords=%v", e.name, gated, e.keywords)

			continue
		}

		if !gated {
			continue
		}

		var want []string
		for _, k := range e.keywords {
			want = append(want, fold(k))
		}

		if !reflect.DeepEqual(c.keywords, want) {
			t.Errorf("%s keywords\n got  %q\n want %q", e.name, c.keywords, want)
		}

		if c.window != e.window {
			t.Errorf("%s window = %d, spec says %d", e.name, c.window, e.window)
		}
	}
}
