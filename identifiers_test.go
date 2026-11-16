package pii

import (
	"fmt"
	"reflect"
	"strconv"
	"strings"
	"testing"
)

// Mirrors tests/test_identifiers.py. Test numbers are computed from the public
// algorithms (pick a body, derive the check), never copied from another
// library's test vectors. The golden corpus holds the bulk of the cases.

type hit struct {
	entity Entity
	text   string
}

func found(text string) []hit {
	var out []hit
	for _, f := range DefaultAnalyzer().Analyze(text) {
		out = append(out, hit{f.Entity, f.Text})
	}

	return out
}

func nirFor(body13 string) string {
	digits := body13
	switch strings.ToUpper(body13[5:7]) {
	case "2A":
		digits = body13[:5] + "19" + body13[7:]
	case "2B":
		digits = body13[:5] + "18" + body13[7:]
	}

	n, _ := strconv.ParseUint(digits, 10, 64)

	return fmt.Sprintf("%s%02d", body13, 97-n%97)
}

func groupNIR(v string) string {
	return strings.Join([]string{v[:1], v[1:3], v[3:5], v[5:7], v[7:10], v[10:13], v[13:]}, " ")
}

func TestFRNIR(t *testing.T) {
	v := nirFor("2931612345678")
	for _, s := range []string{v, groupNIR(v), strings.ReplaceAll(groupNIR(v), " ", "."), strings.ReplaceAll(groupNIR(v), " ", "-")} {
		if !validFRNIR(s) {
			t.Errorf("valid NIR rejected: %q", s)
		}
	}

	for _, dept := range []string{"2A", "2B"} {
		c := nirFor("19115" + dept + "004017")
		if !validFRNIR(c) || !validFRNIR(strings.ToLower(c)) {
			t.Errorf("Corsican NIR rejected: %q", c)
		}
	}

	if validFRNIR(strings.Replace(nirFor("191152A004017"), "2A", "2B", 1)) {
		t.Error("2A key accepted under 2B")
	}

	w := nirFor("1661599123456")
	changed := w[:8] + strconv.Itoa((int(w[8]-'0')+1)%10) + w[9:]

	if validFRNIR(changed) || validFRNIR("3"+w[1:]) {
		t.Error("changed digit or bad sex digit accepted")
	}
}

func TestGroupedNIRIsNotPhone(t *testing.T) {
	g := groupNIR(nirFor("2711864231009"))

	if got, want := found("NIR : "+g+"."), []hit{{EntityFRNIR, g}}; !reflect.DeepEqual(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
}

func TestNIRInsideLongerRunIsNotClaimed(t *testing.T) {
	v := nirFor("2711864231009")

	for _, text := range []string{"ref 9" + v, "ref " + v + "7", "ref 12 " + v} {
		for _, h := range found(text) {
			if h.entity == EntityFRNIR {
				t.Errorf("%q: NIR claimed inside a longer run: %v", text, h)
			}
		}
	}
}

func taxIDFor(head10 string) string {
	n, _ := strconv.ParseUint(head10, 10, 64)

	return fmt.Sprintf("%s%03d", head10, n%511)
}

func TestFRTaxID(t *testing.T) {
	v := taxIDFor("0000000042")
	grouped := strings.Join([]string{v[:2], v[2:4], v[4:7], v[7:10], v[10:]}, " ")

	if !validFRTaxID(v) || !validFRTaxID(grouped) {
		t.Errorf("valid tax id rejected: %q", v)
	}

	if validFRTaxID(v[:12]+strconv.Itoa((int(v[12]-'0')+1)%10)) || validFRTaxID(taxIDFor("4000000042")) {
		t.Error("changed digit or first digit 4 accepted")
	}

	g := taxIDFor("0000000043")
	g = strings.Join([]string{g[:2], g[2:4], g[4:7], g[7:10], g[10:]}, " ")

	if got, want := found("numéro fiscal "+g), []hit{{EntityFRTaxID, g}}; !reflect.DeepEqual(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
}

func luhnComplete(body string) string {
	for d := '0'; d <= '9'; d++ {
		if luhnValid(body + string(d)) {
			return body + string(d)
		}
	}

	panic("unreachable")
}

func digitSum(s string) int {
	sum := 0
	for i := 0; i < len(s); i++ {
		sum += int(s[i] - '0')
	}

	return sum
}

func TestFRSIRENSIRET(t *testing.T) {
	siren := luhnComplete("00012345")
	if !validFRSIREN(siren) || !validFRSIREN(siren[:3]+" "+siren[3:6]+" "+siren[6:]) {
		t.Errorf("valid SIREN rejected: %s", siren)
	}

	siret := luhnComplete(siren + "0001")
	if !validFRSIRET(siret) {
		t.Errorf("valid SIRET rejected: %s", siret)
	}

	// La Poste: digit sum mod 5 == 0, this one fails Luhn.
	if !validFRSIRET("35600000012341") || luhnValid("35600000012341") || validFRSIRET("35600000012342") {
		t.Error("La Poste digit-sum rule not applied")
	}

	// 14 digits that pass Luhn are not a SIRET when the embedded SIREN fails it.
	if badSIREN := "000123450"; luhnValid(badSIREN) || validFRSIRET(luhnComplete(badSIREN+"0001")) {
		t.Error("SIRET with a Luhn-invalid SIREN accepted")
	}

	// La Poste's head office numbers are Luhn-valid; the digit-sum rule is the
	// establishments' exception, not a replacement.
	if head := luhnComplete("3560000000001"); !validFRSIRET(head) || digitSum(head)%5 == 0 {
		t.Errorf("Luhn-valid La Poste SIRET rejected (or test value also passes the digit sum): %s", head)
	}

	grouped := siret[:3] + " " + siret[3:6] + " " + siret[6:9] + " " + siret[9:]
	bad := grouped[:len(grouped)-1] + strconv.Itoa((int(grouped[len(grouped)-1]-'0')+1)%10)
	// A published Diners test card whose first nine digits also pass Luhn.
	diners := "36438999960016"

	cases := []struct {
		text string
		want []hit
	}{
		{"SIREN " + siren, []hit{{EntityFRSIREN, siren}}},
		{"Numéro d'identification : " + siren, []hit{{EntityFRSIREN, siren}}},
		{"order " + siren + " shipped", nil},
		{siren + " is our siren", nil},
		{"SIRET : " + grouped, []hit{{EntityFRSIRET, grouped}}},
		{"SIRET : " + bad, []hit{{EntityPhone, bad}}},
		{"SIRET : " + strings.ReplaceAll(bad, " ", ""), nil},
		{"siret " + diners, []hit{{EntityFRSIRET, diners}}},
		// decomposed (NFD) keyword: e + U+0301
		{"Nume\u0301ro d'entreprise : " + siren, []hit{{EntityFRSIREN, siren}}},
		// the whole keyword must fit in the 40 characters before the number
		{"siren" + strings.Repeat(" ", 35) + siren, []hit{{EntityFRSIREN, siren}}},
		{"siren" + strings.Repeat(" ", 36) + siren, nil},
		{"ref " + diners, []hit{{EntityCreditCard, diners}}},
	}

	for _, c := range cases {
		if got := found(c.text); !reflect.DeepEqual(got, c.want) {
			t.Errorf("%q: got %v, want %v", c.text, got, c.want)
		}
	}
}

func TestESDNINIE(t *testing.T) {
	n := 99151623
	dni := fmt.Sprintf("%08d%c", n, esIDLetters[n%23])

	for _, form := range []string{dni, dni[:8] + "-" + dni[8:], dni[:2] + "." + dni[2:5] + "." + dni[5:8] + "-" + dni[8:]} {
		if !validESDNI(form) {
			t.Errorf("valid DNI rejected: %q", form)
		}
	}

	other := func(v string) string {
		if v[len(v)-1] == 'A' {
			return v[:len(v)-1] + "B"
		}

		return v[:len(v)-1] + "A"
	}

	if validESDNI(other(dni)) {
		t.Error("wrong DNI letter accepted")
	}

	// X and Y bodies are fully issued except 0000000; a Z body starting with 9 is unissued.
	for i, prefix := range []string{"X", "Y", "Z"} {
		body := map[string]string{"X": "0000000", "Y": "0000000", "Z": "9481516"}[prefix]
		m, _ := strconv.Atoi(strconv.Itoa(i) + body)
		nie := fmt.Sprintf("%s%s%c", prefix, body, esIDLetters[m%23])

		if !validESNIE(nie) || !validESNIE(prefix+"-"+body+"-"+nie[8:]) || validESNIE(other(nie)) {
			t.Errorf("NIE check wrong for %q", nie)
		}

		if got, want := found("NIE: "+nie+"."), []hit{{EntityESNIE, nie}}; !reflect.DeepEqual(got, want) {
			t.Errorf("got %v, want %v", got, want)
		}
	}

	if got, want := found("DNI "+dni), []hit{{EntityESDNI, dni}}; !reflect.DeepEqual(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}

	if got := found("el pedido " + dni[:8] + " " + strings.ToLower(dni[8:]) + " más"); got != nil {
		t.Errorf("lowercase letter matched: %v", got)
	}
}
