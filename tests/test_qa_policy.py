from production_control import qa_policy


def test_legacy_5_6_routes_remain_available_for_compatibility():
    assert qa_policy.qa_model_for_execution("gpt-5.6-luna") == "gpt-5.6-terra"
    assert qa_policy.qa_model_for_execution("gpt-5.6-terra") == "gpt-5.6-sol"
    assert qa_policy.qa_model_for_execution("gpt-5.6-sol") == "gpt-5.6-luna"


def test_gpt_6_routes_always_move_to_a_higher_available_reviewer():
    assert qa_policy.qa_model_for_execution("gpt-6-luna") == "gpt-6-sol"
    assert qa_policy.qa_model_for_execution("gpt-6-sol") == "gpt-6.1-sol"
    assert qa_policy.qa_model_for_execution("gpt-6.1-sol") == "gpt-5.6-terra"  # explicit user route


def test_highest_model_and_unavailable_terra_fail_closed():
    assert qa_policy.qa_model_for_execution("gpt-6-astra") is None
    assert qa_policy.qa_model_for_execution("gpt-6-terra") is None
    assert qa_policy.qa_model_for_execution("glm-5.3-flash") is None
    for model in ("gpt-6-astra", "gpt-6-terra", "glm-5.3-flash"):
        allowed, reason = qa_policy.qa_model_allowed(
            "G5", "gpt-6-astra", execution_model=model
        )
        assert not allowed
        assert "没有配置 QA 路由" in reason


def test_only_the_routed_model_is_allowed_to_qa_the_gate():
    assert qa_policy.qa_model_allowed(
        "G5", "gpt-5.6-terra", execution_model="gpt-5.6-luna"
    ) == (True, "")
    allowed, reason = qa_policy.qa_model_allowed(
        "G5", "gpt-5.6-sol", execution_model="gpt-5.6-luna"
    )
    assert not allowed
    assert "应由 gpt-5.6-terra QA" in reason
    assert qa_policy.qa_model_allowed(
        "G5", "gpt-6-sol", execution_model="gpt-6-luna"
    ) == (True, "")
    allowed, reason = qa_policy.qa_model_allowed(
        "G5", "gpt-6-luna", execution_model="gpt-6-luna"
    )
    assert not allowed
    assert "应由 gpt-6-sol QA" in reason


def test_glm_is_neither_qa_nor_trace_writer():
    qa_ok, _ = qa_policy.qa_model_allowed("G5", "glm-5.3-flash")
    writer_ok, reason = qa_policy.writer_model_allowed("glm-5.3-flash")
    assert not qa_ok
    assert not writer_ok
    assert "只有路由表中的 QA 模型" in reason
