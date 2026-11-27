# Ghost AI quality evaluation and fine-tuning preparation

## Current model integration

The application currently calls an OpenAI-compatible chat-completions endpoint.
The configured model defaults to `notrack-uncensored` through `NR_MODEL`.
This repository does not contain a confirmed provider fine-tuning endpoint, job API,
or model-artifact deployment workflow. Therefore these files are a preparation
and evaluation set; they do not fine-tune the remote model by themselves.

## What changed

- Expanded the Arabic system instructions in both `chat.mjs` and `api/chat.mjs`.
- Lowered sampling temperature from 0.7 to 0.35 for more consistent answers.
- Increased the completion budget from 2048 to 3072 tokens for complex tasks.
- Preserved the existing model name, API URL, API key handling, streaming, and tool protocol.

## Evaluation

Use `evaluation.jsonl` as a human-reviewed regression suite. Each row defines
an input and measurable acceptance criteria. Test the same cases before and
after any prompt/model change. Score each criterion 0 or 1 and compare:
- task completion
- context retention
- dialect understanding
- honesty about tools and execution
- factual grounding
- concise communication
- safe handling of secrets and destructive actions

Do not judge quality by eloquence alone. A confident but fabricated execution
claim is a failed test.

## Fine-tuning decision

Before any fine-tuning:
1. Identify the actual upstream provider and confirm it supports supervised fine-tuning
   for the exact base model and API account.
2. Confirm accepted data format, language support, pricing, data retention, and model
   deployment process from the provider's official documentation.
3. Collect consented, privacy-scrubbed examples from real interactions.
4. Remove passwords, API keys, personal identifiers, private messages, and sensitive data.
5. Split examples into train/validation/test sets by conversation, not random individual turns.
6. Compare the fine-tuned model against the base model on the held-out evaluation suite.
7. Keep the base model available for rollback.

Never upload user conversations to a training provider without explicit authorization.
