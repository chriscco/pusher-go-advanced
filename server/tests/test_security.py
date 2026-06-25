from app.auth.security import hash_password, verify_password, generate_token


def test_hash_password_is_not_plaintext():
    h = hash_password("hunter2")
    assert h != "hunter2"
    assert isinstance(h, str)


def test_verify_password_roundtrip():
    h = hash_password("hunter2")
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


def test_generate_token_length_and_uniqueness():
    t1 = generate_token()
    t2 = generate_token()
    assert len(t1) == 128
    assert t1 != t2
