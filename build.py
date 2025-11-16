#!/usr/bin/env python3
"""
Podman Build and Push Script for Senex Trader

This script builds the Django application container image and pushes it to Gitea registry.
Supports versioning, automatic Git-based tagging, and comprehensive error handling.

Usage:
    python build.py [options]

Examples:
    python build.py                          # Build and push with auto-generated tag
    python build.py --tag v1.2.3            # Build and push with specific tag
    python build.py --no-push               # Build only, don't push
    python build.py --platform linux/amd64  # Build for specific platform
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def load_developer_config(project_dir: Path | None = None) -> dict:
    """
    Load developer-specific configuration from .senex_trader.json

    This configuration is REQUIRED. The build will fail if the config file
    doesn't exist. Copy .senex_trader.json.example to .senex_trader.json
    and customize for your environment.

    Args:
        project_dir: Project directory to search for config (defaults to script parent)

    Returns:
        dict: Configuration values from file

    Raises:
        SystemExit: If config file is missing or invalid
    """
    if project_dir is None:
        # Config is in same directory as build.py (monorepo structure)
        project_dir = Path(__file__).parent

    config_path = project_dir / ".senex_trader.json"

    if not config_path.exists():
        print("❌ ERROR: Configuration file not found!")
        print(f"   Expected location: {config_path}")
        print()
        print("📝 Setup instructions:")
        print(f"   1. Copy the example config:")
        print(f"      cp {project_dir}/.senex_trader.json.example {config_path}")
        print(f"   2. Edit {config_path} with your settings")
        print(f"   3. Run build.py again")
        print()
        sys.exit(1)

    try:
        with open(config_path) as f:
            config = json.load(f)
            print(f"📝 Loaded developer config from: {config_path}")
            return config
    except json.JSONDecodeError as e:
        print(f"❌ ERROR: Could not parse {config_path}: {e}")
        sys.exit(1)


class PodmanBuilder:
    """Handles Podman container image building and pushing operations."""

    def __init__(
        self,
        registry: str = "gitea.andermic.net",
        owner: str = "endthestart",
        image_name: str = "senex-trader",
        project_dir: str | None = None,
    ):
        self.registry = registry
        self.owner = owner
        self.image_name = image_name
        self.full_image_name = f"{registry}/{owner}/{image_name}"
        # Use provided project_dir, or default to script's parent directory
        self.project_root = Path(project_dir) if project_dir else Path(__file__).parent

    def get_git_info(self) -> dict:
        """Get Git repository information for tagging."""
        try:
            # Get current commit hash
            commit_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.project_root,
                text=True,
            ).strip()

            # Get current branch
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.project_root,
                text=True,
            ).strip()

            # Check if working directory is clean
            status = subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=self.project_root, text=True
            ).strip()

            is_dirty = bool(status)

            return {"commit": commit_hash, "branch": branch, "is_dirty": is_dirty}
        except subprocess.CalledProcessError as e:
            print(f"Warning: Could not get Git information: {e}")
            return {"commit": "unknown", "branch": "unknown", "is_dirty": False}

    def generate_tag(self, custom_tag: str | None = None) -> str:
        """Generate image tag based on Git info or custom tag."""
        if custom_tag:
            return custom_tag

        git_info = self.get_git_info()
        timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d-%H%M%S")

        # Create tag from branch and commit
        tag = f"{git_info['branch']}-{git_info['commit']}-{timestamp}"

        if git_info["is_dirty"]:
            tag += "-dirty"

        # Clean tag for container registry (replace invalid characters)
        return tag.replace("/", "-").replace("_", "-").lower()

    def check_podman(self) -> bool:
        """Check if Podman is available and running."""
        try:
            subprocess.run(["podman", "--version"], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("❌ Podman is not available or not running")
            print("   Install Podman: https://podman.io/getting-started/installation")
            return False

    def podman_login(self) -> bool:
        """Authenticate with the container registry."""
        print(f"🔐 Logging in to registry {self.registry}...")
        try:
            # Attempt login
            login_result = subprocess.run(
                ["podman", "login", self.registry], check=False, timeout=30
            )

            if login_result.returncode == 0:
                print(f"✅ Successfully logged in to {self.registry}")
                return True
            print(f"❌ Failed to login to {self.registry}")
            print("Please ensure you have valid credentials and try again.")
            return False

        except subprocess.TimeoutExpired:
            print(f"❌ Login timeout for registry {self.registry}")
            return False
        except Exception as e:
            print(f"❌ Login failed: {e}")
            return False

    def check_registry_connectivity(self) -> bool:
        """Check if the container registry is accessible and authenticate if needed."""
        print(f"🔍 Checking connectivity to registry {self.registry}...")

        # For Gitea registry, we need to login first
        if not self.podman_login():
            return False

        print(f"✅ Registry {self.registry} is accessible")
        return True

    def build_image(self, tag: str, platform: str | None = None, no_cache: bool = False) -> bool:
        """Build the container image."""
        print(f"🔨 Building container image: {self.full_image_name}:{tag}")

        build_args = [
            "podman",
            "build",
            "-f",
            "docker/Dockerfile",
            "--layers",  # Enable caching
            "--tag",
            f"{self.full_image_name}:{tag}",
            "--tag",
            f"{self.full_image_name}:latest",
        ]

        if platform:
            build_args.extend(["--platform", platform])

        if no_cache:
            build_args.append("--no-cache")

        # Add build context (current directory)
        build_args.append(".")

        try:
            print(f"📝 Build command: {' '.join(build_args)}")

            # Run build with real-time output
            process = subprocess.Popen(
                build_args,
                cwd=self.project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            # Stream output in real-time
            for line in process.stdout:
                print(line.rstrip())

            process.wait()

            if process.returncode == 0:
                print(f"✅ Successfully built {self.full_image_name}:{tag}")
                return True
            print(f"❌ Build failed with exit code {process.returncode}")
            return False

        except Exception as e:
            print(f"❌ Build failed: {e}")
            return False

    def push_image(self, tag: str) -> bool:
        """Push the container image to the registry."""
        print("📤 Pushing image to registry...")

        images_to_push = [
            f"{self.full_image_name}:{tag}",
            f"{self.full_image_name}:latest",
        ]

        for image in images_to_push:
            try:
                print(f"📤 Pushing {image}...")

                process = subprocess.Popen(
                    ["podman", "push", image],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                )

                # Stream output in real-time
                for line in process.stdout:
                    print(line.rstrip())

                process.wait()

                if process.returncode == 0:
                    print(f"✅ Successfully pushed {image}")
                else:
                    print(f"❌ Failed to push {image}")
                    return False

            except Exception as e:
                print(f"❌ Push failed: {e}")
                return False

        return True

    def get_image_info(self, tag: str) -> dict:
        """Get information about the built image."""
        try:
            result = subprocess.check_output(
                ["podman", "inspect", f"{self.full_image_name}:{tag}"], text=True
            )

            info = json.loads(result)[0]

            return {
                "id": info["Id"][:12],
                "created": info["Created"],
                "size": info["Size"],
                "architecture": info["Architecture"],
                "os": info["Os"],
            }
        except Exception as e:
            print(f"Warning: Could not get image info: {e}")
            return {}

    def build_and_push(
        self,
        tag: str | None = None,
        platform: str | None = None,
        no_cache: bool = False,
        no_push: bool = False,
    ) -> bool:
        """Main method to build and optionally push the image."""

        # Pre-flight checks
        if not self.check_podman():
            return False

        if not no_push and not self.check_registry_connectivity():
            return False

        # Generate tag
        final_tag = self.generate_tag(tag)
        print(f"🏷️  Using tag: {final_tag}")

        # Build image
        if not self.build_image(final_tag, platform, no_cache):
            return False

        # Get image info
        image_info = self.get_image_info(final_tag)
        if image_info:
            print("📊 Image Info:")
            print(f"   ID: {image_info.get('id', 'unknown')}")
            print(f"   Architecture: {image_info.get('architecture', 'unknown')}")
            print(f"   OS: {image_info.get('os', 'unknown')}")
            if "size" in image_info:
                size_mb = image_info["size"] / (1024 * 1024)
                print(f"   Size: {size_mb:.1f} MB")

        # Push image
        if not no_push:
            if not self.push_image(final_tag):
                return False
            print(f"🎉 Successfully built and pushed {self.full_image_name}:{final_tag}")
            print("\n📝 Next steps:")
            print("   Deploy using instructions in senex_trader_docs/deployment")
        else:
            print(f"🎉 Successfully built {self.full_image_name}:{final_tag} (not pushed)")
            print("\n💡 To push manually:")
            print(f"   podman push {self.full_image_name}:{final_tag}")

        return True


def main():
    """Main entry point for the build script."""
    # Load developer config (REQUIRED - will exit if not found)
    dev_config = load_developer_config()

    parser = argparse.ArgumentParser(
        description="Build and push Podman image for Senex Trader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build.py                          # Build and push with config defaults
  python build.py --tag v1.2.3            # Build and push with specific tag
  python build.py --no-push               # Build only, don't push
  python build.py --platform linux/amd64  # Build for specific platform
  python build.py --no-cache              # Build without using cache

Config File:
  Copy .senex_trader.json.example to .senex_trader.json and customize.
  Command-line arguments override config file values.
        """,
    )

    parser.add_argument(
        "--tag",
        "-t",
        help="Custom tag for the image (default: auto-generated from Git info)",
    )

    parser.add_argument(
        "--registry",
        "-r",
        default=dev_config.get("registry"),
        help=f"Container registry URL (from config: {dev_config.get('registry')})",
    )

    parser.add_argument(
        "--owner",
        "-o",
        default=dev_config.get("owner"),
        help=f"Registry owner/username (from config: {dev_config.get('owner')})",
    )

    parser.add_argument(
        "--image-name",
        "-n",
        default=dev_config.get("image_name"),
        help=f"Image name (from config: {dev_config.get('image_name')})",
    )

    parser.add_argument(
        "--platform",
        "-p",
        help="Target platform (e.g., linux/amd64, linux/arm64)",
    )

    parser.add_argument("--no-cache", action="store_true", help="Build without using cache")

    parser.add_argument(
        "--project-dir",
        "-d",
        default=dev_config.get("project_dir"),
        help="Project directory containing Dockerfile (default: script's parent directory)",
    )

    parser.add_argument(
        "--no-push",
        action="store_true",
        default=dev_config.get("default_no_push", False),
        help="Build image but don't push to registry",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    # Validate required config values
    if not args.registry:
        print("❌ ERROR: 'registry' must be set in .senex_trader.json")
        sys.exit(1)
    if not args.owner:
        print("❌ ERROR: 'owner' must be set in .senex_trader.json")
        sys.exit(1)
    if not args.image_name:
        print("❌ ERROR: 'image_name' must be set in .senex_trader.json")
        sys.exit(1)

    # Create builder instance
    builder = PodmanBuilder(
        registry=args.registry,
        owner=args.owner,
        image_name=args.image_name,
        project_dir=args.project_dir,
    )

    print("🚀 Senex Trader - Podman Build Script")
    print("=" * 50)
    print(f"Registry: {builder.registry}")
    print(f"Owner: {builder.owner}")
    print(f"Image: {builder.image_name}")
    print(f"Full image name: {builder.full_image_name}")

    if args.verbose:
        git_info = builder.get_git_info()
        print(f"Git branch: {git_info['branch']}")
        print(f"Git commit: {git_info['commit']}")
        print(f"Working directory clean: {not git_info['is_dirty']}")

    print("=" * 50)

    # Build and push
    success = builder.build_and_push(
        tag=args.tag,
        platform=args.platform,
        no_cache=args.no_cache,
        no_push=args.no_push,
    )

    if success:
        print("\n🎉 Build completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Build failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
