"""Fine-tuning / alignment for coding agents (reward models, rejection sampling, static analysis gates)."""

from ml_core import configure_logging

logger = configure_logging(__name__)


def describe_agent_finetune_playbook() -> dict:
    """Execute the describe agent finetune playbook routine."""
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
    """Execute the main routine."""
    import json

    logger.info(json.dumps(describe_agent_finetune_playbook(), indent=2))


if __name__ == "__main__":
    main()
