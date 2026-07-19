def test_ci_tripwire_deliberately_red():
    assert False, "CI tripwire — this commit must turn the python job red"
