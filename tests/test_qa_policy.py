from production_control import qa_policy


def test_execution_model_uses_the_explicit_independent_gpt_route():
    assert qa_policy.qa_model_for_execution("gpt-5.6-luna") == "gpt-5.6-terra"
    assert qa_policy.qa_model_for_execution("gpt-5.6-terra") == "gpt-5.6-sol"
    assert qa_policy.qa_model_for_execution("gpt-5.6-sol") == "gpt-5.6-luna"


def test_unknown_execution_model_fails_closed():
    assert qa_policy.qa_model_for_execution("glm-5.3-flash") is None
    allowed, reason = qa_policy.qa_model_allowed(
        "G5", "gpt-5.6-terra", execution_model="glm-5.3-flash"
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


def test_glm_is_neither_qa_nor_trace_writer():
    qa_ok, _ = qa_policy.qa_model_allowed("G5", "glm-5.3-flash")
    writer_ok, reason = qa_policy.writer_model_allowed("glm-5.3-flash")
    assert not qa_ok
    assert not writer_ok
    assert "只有路由表中的 QA 模型" in reason

