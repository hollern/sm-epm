def test_imports():
    import anaplan_sdk
    import pigment
    import sm_epm

    assert sm_epm
    assert pigment.PigmentClient
    assert anaplan_sdk.Client
