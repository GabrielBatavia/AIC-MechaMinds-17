from app.infra.regex.bpom_validator import RegexBpomValidator

def test_valid_na():
    v = RegexBpomValidator()
    out = v.validate("Kode: NA18191231707")
    assert out.number and out.number.startswith("NA")