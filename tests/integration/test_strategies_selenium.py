#!/usr/bin/env python
"""
End-to-end Selenium script to test all strategy suggestion generation.

Connects to running Django dev server and tests the actual user flow:
- Login
- Verify DRY-RUN MODE badge
- Verify System Status (Streaming, WebSocket, Data Stream)
- Navigate to /trading/ page
- Switch to manual mode
- Test each strategy from dropdown
- Also test /trading/senex-trident/ separately

Requirements:
    1. Start dev server: python manage.py runserver
    2. Install selenium: pip install selenium
    3. Run this script: python test_strategies_selenium.py

Usage:
    # Default (headless mode)
    python test_strategies_selenium.py

    # With visible browser
    HEADLESS=false python test_strategies_selenium.py

    # Custom server URL
    SERVER_URL=http://localhost:8000 python test_strategies_selenium.py
"""

import getpass
import os
import sys
import time
from pathlib import Path

import pytest

# Skip this module if selenium is not installed
pytest.importorskip("selenium", reason="Selenium not installed")

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

# Configuration
SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:8000")
TEST_EMAIL = os.environ.get("TEST_USER_EMAIL", "test@example.com")
GENERATION_TIMEOUT = 90  # seconds to wait for WebSocket response
SCREENSHOT_DIR = Path(__file__).parent / "selenium_failures"


def create_chrome_driver():
    """Create and configure Chrome WebDriver."""
    chrome_options = Options()
    if os.environ.get("HEADLESS", "true").lower() != "false":
        chrome_options.add_argument("--headless=new")
    else:
        pass  # Visible browser mode

    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])

    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.implicitly_wait(10)
        return driver
    except Exception as e:
        print("ERROR: Failed to initialize Chrome WebDriver.")
        print("Make sure chromedriver is installed: pip install webdriver-manager")
        print(f"Error: {e}")
        sys.exit(1)


def verify_dry_run_badge(driver):
    """Verify DRY-RUN MODE badge visible. Aborts tests if not found."""
    print("\nVerifying DRY-RUN MODE badge...", end=" ", flush=True)
    try:
        badge_elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'DRY-RUN MODE')]")

        if not badge_elements:
            screenshot = take_screenshot(driver, "dry_run_badge", "missing")
            print("\n[FAIL] CRITICAL: DRY-RUN MODE badge NOT FOUND")
            print(f"Screenshot: {screenshot}")
            print("\nABORTING TESTS - Cannot verify dry-run mode is active!")
            print("Ensure TASTYTRADE_DRY_RUN=True in your .env file")
            return False

        # Verify badge is visible
        badge = badge_elements[0]
        if not badge.is_displayed():
            screenshot = take_screenshot(driver, "dry_run_badge", "hidden")
            print("\n[FAIL] CRITICAL: DRY-RUN MODE badge exists but is hidden")
            print(f"Screenshot: {screenshot}")
            return False

        print("[OK]")
        print("   Badge confirmed - dry-run mode active, safe to test\n")
        return True

    except Exception as e:
        screenshot = take_screenshot(driver, "dry_run_badge", "error")
        print(f"\n[FAIL] CRITICAL: Error checking DRY-RUN badge: {e}")
        print(f"Screenshot: {screenshot}")
        return False


def verify_system_status(driver):
    """Verify System Status section shows all services connected."""
    print("Verifying System Status...", end=" ", flush=True)
    try:
        # Navigate to dashboard
        driver.get(f"{SERVER_URL}/dashboard/")

        # Wait for system status section to be present
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'System Status')]"))
        )

        # Check for expected status indicators
        required_statuses = [
            ("Streaming Status:", "Connected"),
            ("WebSocket:", "Connected"),
            ("Data Stream:", "Active"),
        ]

        missing_statuses = []
        for label, expected_value in required_statuses:
            try:
                # Find the label element
                label_elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{label}')]")
                if not label_elements:
                    missing_statuses.append(f"{label} label not found")
                    continue

                # Get parent element and check if expected value is nearby
                parent = label_elements[0].find_element(By.XPATH, "./..")
                if expected_value not in parent.text:
                    missing_statuses.append(
                        f"{label} {expected_value} not found (found: {parent.text.strip()})"
                    )
            except Exception as e:
                missing_statuses.append(f"{label} check failed: {e}")

        if missing_statuses:
            screenshot = take_screenshot(driver, "system_status", "verification_failed")
            print("\n[FAIL] CRITICAL: System Status verification failed")
            print(f"Screenshot: {screenshot}")
            for status in missing_statuses:
                print(f"   - {status}")
            print("\nABORTING TESTS - System services not ready")
            return False

        print("[OK]")
        print("   All services connected and active\n")
        return True

    except Exception as e:
        screenshot = take_screenshot(driver, "system_status", "error")
        print(f"\n[FAIL] CRITICAL: Error checking System Status: {e}")
        print(f"Screenshot: {screenshot}")
        return False


def main():
    """Run end-to-end tests for all strategies."""
    print(f"\n{'=' * 80}")
    print("Selenium E2E Test - Strategy Suggestion Generation + Execution")
    print(f"{'=' * 80}")
    print(f"Server URL: {SERVER_URL}")
    print(f"Testing with user: {TEST_EMAIL}")
    print(f"{'=' * 80}\n")

    # Clear and create screenshot directory
    import shutil

    if SCREENSHOT_DIR.exists():
        shutil.rmtree(SCREENSHOT_DIR)
        print(f"Cleared previous test screenshots from {SCREENSHOT_DIR}")
    SCREENSHOT_DIR.mkdir(exist_ok=True)

    # Prompt for password
    password = getpass.getpass(f"Enter password for {TEST_EMAIL}: ")
    print()

    if os.environ.get("HEADLESS", "true").lower() != "false":
        print("Running in headless mode (set HEADLESS=false to see browser)\n")
    else:
        print("Running with visible browser\n")

    # Create initial driver
    driver = create_chrome_driver()

    try:
        # Login
        login(driver, password)

        if not verify_dry_run_badge(driver):
            print("\nFATAL: Cannot proceed without dry-run mode verification")
            driver.quit()
            sys.exit(1)

        if not verify_system_status(driver):
            print("\nFATAL: System status check failed")
            driver.quit()
            sys.exit(1)

        # Test all strategies on main trading page
        main_results = test_trading_page_strategies(driver)

        # Restart browser for Senex Trident to avoid resource exhaustion
        print(f"\n{'=' * 80}")
        print("Restarting browser for Senex Trident test...")
        print(f"{'=' * 80}\n")
        driver.quit()
        time.sleep(2)  # Brief pause for cleanup
        driver = create_chrome_driver()
        login(driver, password)

        # Test Senex Trident separately with fresh browser
        trident_result = test_senex_trident(driver)

        # Combine results
        all_results = [*main_results, trident_result]

        # Print summary
        print_summary(all_results)

        # Exit code based on results
        passed = sum(1 for r in all_results if r["passed"])
        sys.exit(0 if passed > 0 else 1)

    finally:
        driver.quit()


def login(driver, password):
    """Login to application."""
    print("Logging in...", end=" ", flush=True)

    driver.get(f"{SERVER_URL}/accounts/login/")

    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "username")))
    except TimeoutException:
        screenshot = take_screenshot(driver, "login", "page_not_loaded")
        print("\n[FAIL] Login page did not load")
        print(f"Screenshot: {screenshot}")
        print(f"\nIs the dev server running at {SERVER_URL}?")
        sys.exit(1)

    # Fill in login form
    email_input = driver.find_element(By.NAME, "username")
    password_input = driver.find_element(By.NAME, "password")

    email_input.clear()
    email_input.send_keys(TEST_EMAIL)
    password_input.clear()
    password_input.send_keys(password)

    # Submit form
    login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    login_button.click()

    # Wait for redirect or error
    try:
        WebDriverWait(driver, 15).until(
            lambda d: (
                "/accounts/login/" not in d.current_url
                or len(d.find_elements(By.CSS_SELECTOR, ".alert-danger, .errorlist")) > 0
            )
        )

        if "/accounts/login/" in driver.current_url:
            error_elements = driver.find_elements(By.CSS_SELECTOR, ".alert-danger, .errorlist")
            if error_elements:
                error_text = error_elements[0].text
                screenshot = take_screenshot(driver, "login", "failed")
                print(f"\n[FAIL] Login failed: {error_text}")
                print(f"Screenshot: {screenshot}")
                sys.exit(1)

        print("[OK]")

    except TimeoutException:
        screenshot = take_screenshot(driver, "login", "timeout")
        page_url = driver.current_url
        page_title = driver.title
        print("\n[FAIL] Login timeout after 15s")
        print(f"Current URL: {page_url}")
        print(f"Page title: {page_title}")
        print(f"Screenshot: {screenshot}")

        # Check if we're still on login page or somewhere else
        if "/accounts/login/" in page_url:
            print("\nStill on login page - checking for errors...")
            errors = driver.find_elements(
                By.CSS_SELECTOR, ".alert-danger, .errorlist, .text-danger"
            )
            if errors:
                print(f"Found error: {errors[0].text}")
        sys.exit(1)


@pytest.fixture
def driver():
    """Create Chrome WebDriver for Selenium tests."""
    _driver = create_chrome_driver()
    yield _driver
    _driver.quit()


@pytest.mark.skip(reason="Selenium test requires running server and browser")
def test_trading_page_strategies(driver):
    """Test all strategies on the main /trading/ page."""
    print(f"\n{'=' * 80}")
    print("Testing Strategies on /trading/ Page")
    print(f"{'=' * 80}\n")

    # Navigate to trading page
    driver.get(f"{SERVER_URL}/trading/")

    # Wait for page to load
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "selectionMode")))
    except TimeoutException:
        screenshot = take_screenshot(driver, "trading_page", "load_timeout")
        print("[FAIL] Trading page failed to load")
        print(f"Screenshot: {screenshot}")
        return []

    # Switch to Manual Mode
    print("Switching to Manual Mode...", end=" ", flush=True)
    try:
        mode_select = Select(driver.find_element(By.ID, "selectionMode"))
        mode_select.select_by_value("forced")
        print("[OK]\n")
    except Exception as e:
        print(f"[FAIL] Failed: {e}")
        return []

    # Wait for strategy dropdown to be enabled
    try:
        WebDriverWait(driver, 5).until(
            lambda d: not d.find_element(By.ID, "strategySelect").get_attribute("disabled")
        )
    except TimeoutException:
        print("Warning: Strategy dropdown did not enable")

    # Extract all strategies from dropdown
    print("Extracting strategies from dropdown...", end=" ", flush=True)
    try:
        strategy_select = Select(driver.find_element(By.ID, "strategySelect"))
        strategies = [(opt.get_attribute("value"), opt.text) for opt in strategy_select.options]
        print(f"[OK] Found {len(strategies)} strategies\n")
    except Exception as e:
        print(f"[FAIL] Failed: {e}")
        return []

    # Test each strategy
    results = []
    for idx, (strategy_value, strategy_display) in enumerate(strategies, 1):
        print(f"[{idx}/{len(strategies)}] {strategy_display:<30}", end=" ", flush=True)
        result = generate_suggestion_on_trading_page(driver, strategy_value, strategy_display)
        results.append(result)

        if result["passed"]:
            print("[OK] PASS")
        else:
            print("[FAIL] FAIL")
            print(f"    {result['error']}")
            if result.get("screenshot"):
                print(f"    Screenshot: {result['screenshot']}")

    return results


def generate_suggestion_on_trading_page(driver, strategy_value, strategy_display):
    """Generate suggestion for a specific strategy on /trading/ page."""
    try:
        # Reload page for clean state between strategies
        driver.refresh()
        time.sleep(2)  # Wait for page reload

        # Re-enable manual mode after reload
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "selectionMode"))
            )
            mode_select = Select(driver.find_element(By.ID, "selectionMode"))
            mode_select.select_by_value("forced")
            time.sleep(1)  # Wait for strategy dropdown to enable
        except Exception as e:
            screenshot = take_screenshot(driver, strategy_value, "mode_select_failed")
            return {
                "strategy": strategy_value,
                "display_name": strategy_display,
                "passed": False,
                "error": f"Failed to set manual mode: {e}",
                "screenshot": screenshot,
            }

        # Select the strategy
        strategy_select = Select(driver.find_element(By.ID, "strategySelect"))
        strategy_select.select_by_value(strategy_value)

        # Select QQQ symbol
        symbol_select = Select(driver.find_element(By.ID, "symbolSelect"))
        symbol_select.select_by_value("QQQ")

        # Click generate button
        generate_btn = driver.find_element(By.ID, "generateBtn")

        # Wait for button to be enabled (might be disabled during initialization)
        WebDriverWait(driver, 10).until(lambda d: not generate_btn.get_attribute("disabled"))

        generate_btn.click()

        # Wait for result (success or error)
        return wait_for_generation_result(driver, strategy_value)

    except Exception as e:
        screenshot = take_screenshot(driver, strategy_value, "exception")
        return {
            "strategy": strategy_value,
            "display_name": strategy_display,
            "passed": False,
            "error": str(e),
            "screenshot": screenshot,
        }


def test_senex_trident(driver):
    """Test Senex Trident on its dedicated page."""
    print(f"\n{'=' * 80}")
    print("Testing Senex Trident")
    print(f"{'=' * 80}\n")

    print("[1/1] Senex Trident                  ", end=" ", flush=True)

    # Navigate to senex trident page
    driver.get(f"{SERVER_URL}/trading/senex-trident/")

    try:
        # Wait for page to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "generate-suggestion-btn"))
        )

        # Click generate button
        generate_btn = driver.find_element(By.ID, "generate-suggestion-btn")

        # Wait for button to be enabled
        WebDriverWait(driver, 10).until(lambda d: not generate_btn.get_attribute("disabled"))

        generate_btn.click()

        # Wait for result
        result = wait_for_generation_result(driver, "senex_trident")

        if result["passed"]:
            print("[OK] PASS")
        else:
            print("[FAIL] FAIL")
            print(f"    {result['error']}")
            if result.get("screenshot"):
                print(f"    Screenshot: {result['screenshot']}")

        return result

    except Exception as e:
        screenshot = take_screenshot(driver, "senex_trident", "exception")
        print("[FAIL] FAIL")
        print(f"    {e!s}")
        print(f"    Screenshot: {screenshot}")
        return {
            "strategy": "senex_trident",
            "display_name": "Senex Trident",
            "passed": False,
            "error": str(e),
            "screenshot": screenshot,
        }


def wait_for_generation_result(driver, strategy_name):
    """Wait for generation to complete and return result."""
    try:
        # Wait for either:
        # 1. Suggestion container becomes visible (success)
        # 2. Alert message appears (error or cannot generate)
        # 3. Status alert appears
        WebDriverWait(driver, GENERATION_TIMEOUT).until(
            lambda d: (
                # Success: suggestion container visible
                "d-none" not in d.find_element(By.ID, "suggestionContainer").get_attribute("class")
                or
                # Error: alert message
                len(d.find_elements(By.CSS_SELECTOR, ".alert-danger, .alert-warning")) > 0
                or
                # Status message
                len(d.find_elements(By.ID, "statusAlert")) > 0
            )
        )

        # Check what we got
        suggestion_container = driver.find_element(By.ID, "suggestionContainer")
        is_visible = "d-none" not in suggestion_container.get_attribute("class")

        if is_visible:
            # Success!
            return {
                "strategy": strategy_name,
                "display_name": strategy_name.replace("_", " ").title(),
                "passed": True,
                "error": None,
                "screenshot": None,
            }

        # Check for alerts
        alerts = driver.find_elements(By.CSS_SELECTOR, ".alert-danger, .alert-warning")
        if alerts:
            error_text = alerts[0].text[:200]  # Truncate long errors
            screenshot = take_screenshot(driver, strategy_name, "alert_error")
            return {
                "strategy": strategy_name,
                "display_name": strategy_name.replace("_", " ").title(),
                "passed": False,
                "error": error_text,
                "screenshot": screenshot,
            }

        # Check status alert
        status_alert = driver.find_element(By.ID, "statusAlert")
        if status_alert and status_alert.text:
            error_text = status_alert.text[:200]
            screenshot = take_screenshot(driver, strategy_name, "status_error")
            return {
                "strategy": strategy_name,
                "display_name": strategy_name.replace("_", " ").title(),
                "passed": False,
                "error": error_text,
                "screenshot": screenshot,
            }

        # Unknown state
        screenshot = take_screenshot(driver, strategy_name, "unknown_state")
        return {
            "strategy": strategy_name,
            "display_name": strategy_name.replace("_", " ").title(),
            "passed": False,
            "error": "Unknown state - no success or error indicator found",
            "screenshot": screenshot,
        }

    except TimeoutException:
        screenshot = take_screenshot(driver, strategy_name, "timeout")
        return {
            "strategy": strategy_name,
            "display_name": strategy_name.replace("_", " ").title(),
            "passed": False,
            "error": f"Timeout after {GENERATION_TIMEOUT}s",
            "screenshot": screenshot,
        }


def take_screenshot(driver, strategy_name, reason):
    """Take screenshot on failure."""
    filename = f"{strategy_name}_{reason}_{int(time.time())}.png"
    filepath = SCREENSHOT_DIR / filename
    driver.save_screenshot(str(filepath))
    return filepath


def print_summary(results):
    """Print summary of test results."""
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])

    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total:   {len(results)}")
    print(f"Passed:  {passed}")
    print(f"Failed:  {failed}")

    if failed > 0:
        print(f"\n{'=' * 80}")
        print("FAILED STRATEGIES")
        print(f"{'=' * 80}")
        for r in results:
            if not r["passed"]:
                display_name = r.get("display_name", r["strategy"])
                error = r["error"][:100]  # Truncate long errors
                print(f"{display_name:<30} {error}")

    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
