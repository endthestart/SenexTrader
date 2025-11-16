"""
Position validation utility.
Checks positions for data consistency and completeness.
"""

from decimal import Decimal

from services.core.logging import get_logger

logger = get_logger(__name__)


class PositionValidator:
    """Validate position data for consistency and completeness."""

    def validate_position(self, position) -> list[str]:
        """
        Validate a single position for data issues.

        Args:
            position: Position model instance

        Returns:
            List of issue descriptions (empty if valid)
        """
        issues = []

        # Check required fields
        if not position.symbol:
            issues.append("Missing underlying symbol")

        if not position.trading_account:
            issues.append("Missing trading account reference")

        # Check app-managed positions have required metadata
        if position.is_app_managed:
            metadata = position.metadata or {}

            if not metadata.get("suggestion_id"):
                issues.append(
                    "App-managed position missing suggestion_id "
                    "(required for profit target calculations)"
                )

            if not metadata.get("strikes"):
                issues.append(
                    "App-managed position missing strikes data " "(used for conflict detection)"
                )

            if position.profit_targets_created and not position.profit_target_details:
                issues.append("Profit targets marked created but no details stored")

            # Only warn about missing risk data if position is substantial
            if (
                not position.initial_risk
                and not position.spread_width
                and position.unrealized_pnl
                and abs(Decimal(str(position.unrealized_pnl))) > 100
            ):
                issues.append(
                    "App-managed position missing risk data "
                    "(initial_risk or spread_width recommended for substantial positions)"
                )

        # Check P&L reasonableness (flag unusual values)
        if position.unrealized_pnl:
            pnl = abs(Decimal(str(position.unrealized_pnl)))
            if pnl > 100000:
                issues.append(
                    f"Unusually large P&L: ${position.unrealized_pnl:,.2f} "
                    "(may indicate data issue)"
                )

        # Check for legs data (needed for Greeks calculation)
        metadata = position.metadata or {}
        if not metadata.get("legs"):
            issues.append("Position missing legs data (needed for Greeks calculation)")
        elif len(metadata.get("legs", [])) == 0:
            issues.append("Position has empty legs array")

        # Validate quantity consistency
        if position.quantity == 0 and position.lifecycle_state in {"open_full", "open_partial"}:
            issues.append("Open position has zero quantity")

        # Check for closed positions that should be marked closed
        if position.lifecycle_state in {"open_full", "open_partial"} and position.closed_at:
            issues.append("Position lifecycle is open but closed_at timestamp is populated")

        return issues

    def validate_all_positions(self, user) -> dict:
        """
        Validate all positions for a user.

        Args:
            user: User model instance

        Returns:
            Dict with validation results including:
            - total_positions: Total number of open positions
            - positions_with_issues: Count of positions with problems
            - issues_by_position: Dict mapping position ID to issues
            - summary: List of most common issues
        """
        from trading.models import Position

        positions = Position.objects.filter(
            user=user, lifecycle_state__in=["open_full", "open_partial"]
        )

        results = {
            "total_positions": positions.count(),
            "positions_with_issues": 0,
            "issues_by_position": {},
            "summary": [],
        }

        # Track issue frequency for summary
        issue_counts = {}

        for position in positions:
            issues = self.validate_position(position)
            if issues:
                results["positions_with_issues"] += 1
                results["issues_by_position"][position.id] = {
                    "symbol": position.symbol,
                    "strategy": position.strategy_type,
                    "is_app_managed": position.is_app_managed,
                    "issues": issues,
                }

                # Count issue types
                for issue in issues:
                    # Extract issue type (first part before parenthesis)
                    issue_type = issue.split("(")[0].strip()
                    issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1

        # Create summary of most common issues
        if issue_counts:
            sorted_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)
            results["summary"] = [
                f"{issue}: {count} position(s)" for issue, count in sorted_issues[:5]
            ]

        return results

    def get_health_score(self, user) -> dict:
        """
        Calculate a health score for user's position portfolio.

        Args:
            user: User model instance

        Returns:
            Dict with:
            - score: 0-100 health score
            - grade: A, B, C, D, or F
            - issues: Number of issues found
            - recommendations: List of improvement suggestions
        """
        validation_results = self.validate_all_positions(user)

        total_positions = validation_results["total_positions"]
        positions_with_issues = validation_results["positions_with_issues"]

        if total_positions == 0:
            return {
                "score": 100,
                "grade": "N/A",
                "issues": 0,
                "recommendations": ["No open positions to validate"],
            }

        # Calculate score: 100 - (percentage of positions with issues * 100)
        issue_percentage = (positions_with_issues / total_positions) * 100
        score = max(0, 100 - issue_percentage)

        # Assign grade
        if score >= 90:
            grade = "A"
        elif score >= 80:
            grade = "B"
        elif score >= 70:
            grade = "C"
        elif score >= 60:
            grade = "D"
        else:
            grade = "F"

        # Generate recommendations
        recommendations = []
        if positions_with_issues > 0:
            recommendations.append(f"Review {positions_with_issues} position(s) with data issues")

        # Add specific recommendations based on summary
        for summary_item in validation_results["summary"][:3]:
            if "missing legs data" in summary_item.lower():
                recommendations.append("Sync positions from broker to populate legs data")
            elif "missing suggestion_id" in summary_item.lower():
                recommendations.append("Ensure all app-managed positions link to suggestions")
            elif "missing strikes data" in summary_item.lower():
                recommendations.append("Update position metadata with strike information")

        return {
            "score": round(score, 1),
            "grade": grade,
            "issues": positions_with_issues,
            "total_positions": total_positions,
            "recommendations": recommendations,
        }
