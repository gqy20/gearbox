"""CLI entrypoint."""

import click

from gearbox.commands.agent import agent
from gearbox.commands.cleanup import cleanup, cleanup_restore_unmerged_pr
from gearbox.commands.config import config
from gearbox.commands.dispatch import dispatch
from gearbox.commands.root import audit, package_marketplace, publish_issues, release_notes


@click.group()
@click.version_option(version="0.1.0", prog_name="gearbox")
def cli() -> None:
    """Gearbox - AI 驱动的仓库自动化飞轮系统"""
    pass


cli.add_command(audit)
cli.add_command(publish_issues)
cli.add_command(package_marketplace)
cli.add_command(release_notes)
cli.add_command(agent)
cli.add_command(cleanup)
cli.add_command(cleanup_restore_unmerged_pr)
cli.add_command(dispatch)
cli.add_command(config)


if __name__ == "__main__":
    cli()
