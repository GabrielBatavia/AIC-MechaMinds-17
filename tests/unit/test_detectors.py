from app.domain.detectors import clean_nie

def test_clean_nie():
    assert clean_nie(" gkl 20 1234 3197 a1 ") == "GKL2012343197A1"
