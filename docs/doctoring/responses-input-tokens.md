# Responses input-token count

`POST /v1/responses/input_tokens` is an explicit provider capability route
(issue #1157; [OpenAI reference](https://developers.openai.com/api/reference/typescript/resources/responses/subresources/input_tokens/methods/count)). An
agent is eligible only when its operator configuration contains the
`responses_input_tokens` capability tag; model names never imply support.

The request forwards the documented Responses input-count fields. Gateway
policy fields (`routing`, `zdr_only`, and `attribution`) are consumed by the
gateway and are not sent upstream. The response must contain
`{"object":"response.input_tokens"}` and a non-negative integer
`input_tokens`; booleans and malformed provider objects produce HTTP 502 before
success accounting is recorded.

Nonempty `conversation` and `previous_response_id` references are rejected
with named 400 errors until a principal-bound reference registry exists. Null
or empty optional references are treated as omitted.

This slice does not generate a local count or automatically preflight
generation requests. Shared
conversation budgeting and automatic count generation remain future work.
