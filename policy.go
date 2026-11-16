package pii

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"sort"
)

// Action is what a Policy does with a finding.
type Action string

const (
	// ActionReject drops the whole record and signals it (safest for a public
	// index: refuse rather than half-scrub). This is the default.
	ActionReject Action = "reject"
	// ActionRedact replaces the span with a typed mask, e.g. "[EMAIL]".
	ActionRedact Action = "redact"
	// ActionHash replaces the span with a stable hash, allowing joins without
	// the raw value, e.g. "[EMAIL:9f86d081]".
	ActionHash Action = "hash"
	// ActionTokenize replaces the span with a typed placeholder token. NOTE:
	// this is NOT reversible here; a reversible token needs a vault-backed map.
	ActionTokenize Action = "tokenize"
	// ActionFlag leaves the text untouched (detect-and-report / audit mode).
	ActionFlag Action = "flag"
	// ActionAllow explicitly permits an entity (e.g. a public contact address).
	ActionAllow Action = "allow"
)

// ErrRejected is returned by Apply when a finding matches a reject action.
var ErrRejected = errors.New("pii: record rejected (reject policy matched)")

// Policy maps entities to actions. Default applies to any entity without an
// explicit entry. The zero Policy rejects everything (safe by default).
type Policy struct {
	Default  Action
	ByEntity map[Entity]Action
}

// RejectAll rejects any detected entity (the safe default for public indices).
func RejectAll() Policy { return Policy{Default: ActionReject} }

// RedactAll masks every detected entity in place.
func RedactAll() Policy { return Policy{Default: ActionRedact} }

// FlagAll detects and reports without mutating (audit/observability mode).
func FlagAll() Policy { return Policy{Default: ActionFlag} }

// SpecPolicy returns the per-entity default_policy from spec/entities.yaml: the
// SSOT's recommended posture (cards/IBANs rejected, contact details redacted,
// IPs flagged). Default is reject for any entity not listed.
func SpecPolicy() Policy {
	return Policy{
		Default: ActionReject,
		ByEntity: map[Entity]Action{
			EntityEmail:      ActionRedact,
			EntityFRNIR:      ActionRedact,
			EntityFRTaxID:    ActionRedact,
			EntityFRSIRET:    ActionRedact,
			EntityFRSIREN:    ActionRedact,
			EntityESDNI:      ActionRedact,
			EntityESNIE:      ActionRedact,
			EntityPhone:      ActionRedact,
			EntityCreditCard: ActionReject,
			EntityIBAN:       ActionReject,
			EntityIP:         ActionFlag,
		},
	}
}

func (p Policy) action(e Entity) Action {
	if p.ByEntity != nil {
		if a, ok := p.ByEntity[e]; ok {
			return a
		}
	}

	if p.Default == "" {
		return ActionReject // zero value is safe
	}

	return p.Default
}

// Apply enforces the policy on text given its findings. It returns the
// transformed text, or ErrRejected if any finding's action is reject. Findings
// are applied right-to-left so byte offsets stay valid as the string shrinks/grows.
func (p Policy) Apply(text string, findings []Finding) (string, error) {
	for _, f := range findings {
		if p.action(f.Entity) == ActionReject {
			return "", ErrRejected
		}
	}

	ordered := make([]Finding, len(findings))
	copy(ordered, findings)
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].Start > ordered[j].Start })

	out := text

	for _, f := range ordered {
		repl, replace := p.replacement(f)
		if !replace {
			continue
		}

		out = out[:f.Start] + repl + out[f.End:]
	}

	return out, nil
}

// replacement returns the masked text for a finding and whether to substitute.
func (p Policy) replacement(f Finding) (string, bool) {
	switch p.action(f.Entity) {
	case ActionRedact:
		return "[" + string(f.Entity) + "]", true
	case ActionHash:
		return "[" + string(f.Entity) + ":" + shortHash(f.Text) + "]", true
	case ActionTokenize:
		return "[" + string(f.Entity) + "_TOKEN]", true
	case ActionReject, ActionFlag, ActionAllow:
		return "", false
	default:
		return "", false
	}
}

func shortHash(s string) string {
	sum := sha256.Sum256([]byte(s))

	return hex.EncodeToString(sum[:])[:8]
}
