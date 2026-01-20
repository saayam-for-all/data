# Language Translation With AI fallback Module

This module normalizes multilingual and mixed-language text into English
before it is passed to downstream AI models.

## Purpose
User-generated text often contains mixed languages, slang, and emojis.
Traditional translation fails on such input. This module ensures consistent
English-only input for AI pipelines.

## How it works
1. Python-based language detection and translation
2. Translation quality validation
3. AI fallback using Groq for complex cases

## When AI is used
AI translation is triggered only when deterministic translation is
unsatisfactory (e.g., mixed languages or partial translations).

## Output
Always returns clean English text suitable for ML models.

## Notes
- Optimized for cost and token usage
- AI usage is intentionally minimized

## Experimentation and Validation
The experimentation revealed clear patterns in how the translation module behaves based on input complexity. Clean and single-language inputs were mostly handled by deterministic translation, while mixed-language and noisy inputs frequently required AI-based translation.

## Fallback behavior observed during testing is summarized below:

| Input Type                       | Python Translation | AI Fallback |
|--------------------------------|--------------------|-------------|
| Clean English text              | ~100%              | ~0%         |
| Single-language non-English     | ~70–90%            | ~10–30%     |
| Mixed-language sentences        | ~0–30%             | ~70–100%    |
| Slang, emojis, noisy input     | ~0–20%             | ~80–100%    |

## Conclusion

The experimentation confirms that the translation module behaves as intended. Deterministic translation efficiently handles simple cases, while AI-based translation is invoked only for complex or unreliable inputs. This validates the hybrid approach as robust, predictable, and cost-aware for real-world multilingual text processing.
