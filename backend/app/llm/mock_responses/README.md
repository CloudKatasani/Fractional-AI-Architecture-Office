Optional hand-written mock narratives: `mock_responses/{agent_id}/{tenant_id}_{key}.json` with `{"summary": "...", "notes": []}`.
The key is derived from the run parameters (e.g. the design id); when no file matches, MockLLM renders
`templates/{agent_id}.jinja` over the agent's deterministic facts.
