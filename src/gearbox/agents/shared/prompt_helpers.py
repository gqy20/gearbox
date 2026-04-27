"""Shared prompt formatting helpers."""

from gearbox.core.gh import IssueSummary


def format_issues_summary(
    issues: list[IssueSummary],
    current_issue_number: int | None = None,
    header: str = "其他 Open Issues 概览",
) -> str:
    """
    Format a list of issues into a markdown summary for prompt context.

    Args:
        issues: List of IssueSummary objects.
        current_issue_number: If set, exclude this issue from the summary (e.g. when
            classifying a specific issue, you don't want to show it in "other" issues).
        header: Markdown header to use before the list.
    """
    other = [i for i in issues if i.number != current_issue_number]

    if not other:
        return f"{header}\n\n(无其他 open issues)"

    lines = []
    for issue in other:
        labels_str = ", ".join(issue.labels) if issue.labels else "无标签"
        lines.append(f"- #{issue.number} [{issue.title}]({issue.url}) — {labels_str}")

    return f"{header}\n\n" + "\n".join(lines)
