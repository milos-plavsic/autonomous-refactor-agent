"""Fine-tuning / alignment for coding agents (reward models, rejection sampling, static analysis gates)."""

from ml_core import configure_logging

logger = configure_logging(__name__)


def agent_training_guide() -> dict:
    """Return notes for policy-model fine-tuning on refactor decisions."""
    return {
        "policy_finetune": [
            "SFT on (repo context, accepted patch) pairs from human review.",
            "RLHF/RLAIF with reward = tests pass + linter delta + reviewer score.",
        ],
        "safety": [
            "Freeze tool permissions; fine-tune only the planner LLM with constrained decoding.",
        ],
        "cheap_iteration": "Preference pairs from reviewer-agent vs refactor-agent on same diff.",
    }


def main() -> None:
    """Main."""
    import json

    logger.info(json.dumps(agent_training_guide(), indent=2))


if __name__ == "__main__":
    main()
