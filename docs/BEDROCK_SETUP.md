# Connecting Claude on AWS Bedrock

Bedrock is **optional**, and it covers **planner intent extraction only**. The production default is Gemini on
Vertex AI (`LLM_PROVIDER=gemini`, see [DEPLOYMENT.md](DEPLOYMENT.md)). The ticketing agent and AR guidance use
Gemini, or their non-LLM fallbacks, whatever this page configures.

The app starts, the tests pass, and every demo scenario works without Bedrock, using the deterministic rule-based extractor. With Bedrock,
Claude interprets free text (especially varied Tamil, Tanglish or long
sentences) more flexibly. Its output is still validated and resolved by the same
deterministic code.

Nothing about your AWS account was assumed: no region, model ID or profile is
hard-coded. You must supply verified values.

## Verified configuration (2026-10-10)

| Setting | Value |
|---|---|
| Region | `us-west-2` |
| Model | `us.anthropic.claude-haiku-4-5-20251001-v1:0` (inference profile; about 0.6 s for a short call) |
| Credentials | AWS profile `railsaathi` in `~/.aws/credentials` (temporary STS session credentials) |

Several other profiles appear in `list-inference-profiles` but returned
`AccessDeniedException ... not available for this account` (for example
`claude-haiku-5-5` and `claude-sonnet-5-5`). Being listed does not mean a model
can be invoked, so always test with `scripts/check_bedrock.py`. Confirmed
invokable: Haiku 4.5, Sonnet 4.5, Opus 4.5 and Opus 4.6.

Temporary (`ASIA…`) credentials expire. When that happens, the app logs
`auth_failed`, falls back to rules, and pauses Bedrock for 5 minutes. Paste
fresh values with `aws configure set ... --profile railsaathi` and restart the
backend.

## 1. Credentials (standard AWS credential chain)

Use one of these. **Never** put credentials in the frontend or commit them.

```bash
aws configure                 # access key + secret (stored in ~/.aws/credentials)
# or
aws configure sso             # IAM Identity Center; then: aws sso login --profile <name>
# or: environment variables / instance role / container role on a server
```

Check:

```bash
aws sts get-caller-identity
```

## 2. Find a model you can actually use

```bash
aws bedrock list-inference-profiles --region <region> \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId,'anthropic')].inferenceProfileId"
aws bedrock list-foundation-models --region <region> --by-provider anthropic \
  --query "modelSummaries[].modelId"
```

Newer Claude models are usually invoked through an **inference profile ID**
(for example an ID starting with a geography prefix). Use exactly what the
command prints for your account and region, and make sure model access is
enabled in the Bedrock console.

Required IAM permission: `bedrock:InvokeModel` on the model or inference
profile (the Converse API uses it). Cross-region inference profiles also need
permission on the underlying model ARNs in their regions.

## 3. Configure the backend

Edit `backend/.env` (copied from `.env.example`):

```ini
LLM_PROVIDER=bedrock
AWS_REGION=<your region>
BEDROCK_MODEL_ID=<exact model or inference profile id from step 2>
AWS_PROFILE=<optional named profile>
BEDROCK_TIMEOUT_SECONDS=15
BEDROCK_MAX_RETRIES=2
```

## 4. Verify the live connection

```bash
cd backend
uv run python scripts/check_bedrock.py
```

The script makes one plain Converse call and one structured-extraction call,
then prints the parsed `IntentUpdate`. It prints a hint for each failure kind.

Then restart the backend and check:

```bash
curl http://localhost:8000/api/health
# "ai": {"bedrock_configured": true, "provider": "bedrock", "active": true, ...}
```

Each message response reports `extraction.source` (`bedrock` or `rules`) and,
on fallback, `extraction.fallback_reason`. The UI header shows
"Claude (Bedrock) active" when Bedrock is in use.

## How the integration works

- `app/intent/bedrock.py`: boto3 `bedrock-runtime` client, `converse()` with
  `toolConfig.toolChoice = {"tool": {"name": "record_journey_intent"}}`. That
  forced tool call is the structured-output mechanism. Its input schema is the
  Pydantic `IntentUpdate` JSON schema with `$refs` inlined. The returned
  `toolUse.input` is validated with Pydantic; invalid output raises
  `invalid_output` and the rule-based extractor takes over.
- `temperature: 0`, `maxTokens: 800`, botocore connect and read timeouts, and
  standard retry mode.
- Error mapping:

| Bedrock / botocore error | Kind | Effect |
|---|---|---|
| `NoCredentialsError`, `UnrecognizedClientException`, `ExpiredTokenException`, `InvalidSignatureException` | `auth_failed` | Fallback, Bedrock paused 5 minutes |
| `AccessDeniedException` | `access_denied` | Fallback, paused 5 minutes |
| missing region, model ID or profile | `not_configured` | Fallback |
| `ThrottlingException`, `ServiceQuotaExceededException` | `throttled` | Fallback for that message |
| `ModelTimeoutException`, read/connect timeout, endpoint unreachable | `timeout` | Fallback for that message |
| `ValidationException`, `ResourceNotFoundException`, `ModelErrorException`, others | `model_error` | Fallback for that message |
| Output failing the schema | `invalid_output` | Fallback for that message |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `auth_failed` | `aws sts get-caller-identity`; re-run `aws sso login`; check `AWS_PROFILE` |
| `access_denied` | Enable model access in the console; add `bedrock:InvokeModel` for the model or profile |
| `model_error` with `ValidationException` | The model ID is wrong for that region, or the model requires an inference profile ID |
| `timeout` | Network or proxy to `bedrock-runtime.<region>.amazonaws.com`; raise `BEDROCK_TIMEOUT_SECONDS` |
| Health shows `bedrock_not_configured` | `LLM_PROVIDER=bedrock` is set but `AWS_REGION` or `BEDROCK_MODEL_ID` is empty |

Automated tests never call AWS. `tests/test_bedrock.py` uses botocore's `Stubber`
and mocks for every error path.
