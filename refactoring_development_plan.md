# Refactoring and Development Plan

This document outlines a phased approach to address the critical issues identified in the golf simulation project. Each phase targets a specific area of improvement, with clear steps to guide the development process.

---

### Phase 1: Consolidate Dependency Management [Completed]

**Goal:** Establish a single source of truth for project dependencies to improve consistency and simplify environment setup.

**Issue:** The project currently uses both a `pyproject.toml` file for Poetry and a `requirements.txt` file, leading to potential dependency conflicts and confusion.

**Steps:**

1.  **Audit and Merge Dependencies:** [Completed]
    *   Compare `requirements.txt` and `pyproject.toml`.
    *   Add any missing dependencies from `requirements.txt` to the `[tool.poetry.dependencies]` or `[tool.poetry.group.dev.dependencies]` sections of `pyproject.toml`.

2.  **Remove `requirements.txt`:** [Completed]
    *   Once all dependencies are consolidated in `pyproject.toml`, delete the `requirements.txt` file.

3.  **Update Documentation:** [Completed]
    *   Modify the `README.md` file to remove any references to `requirements.txt`.
    *   Update the setup instructions to exclusively use Poetry commands (e.g., `poetry install`).

---

### Phase 2: Refactor Delivery Service [Completed]

**Goal:** Eliminate code duplication and create a single, flexible delivery service module.

**Issue:** The `SingleRunnerDeliveryService` and `MultiRunnerDeliveryService` classes in `golfsim/simulation/services.py` are largely redundant.

**Steps:**

1.  **Create a Unified `DeliveryService`:** [Completed]
    *   In a new file, `golfsim/simulation/delivery_service.py`, create a new `DeliveryService` class.
    *   This class will be initialized with a `num_runners` parameter.

2.  **Merge Logic:** [Completed]
    *   Move the shared logic (configuration, logging, distance calculation) from the old classes into the new `DeliveryService`.
    *   Incorporate the runner management and dispatching logic from `MultiRunnerDeliveryService`, ensuring it scales down to a single runner.

3.  **Replace Old Classes:** [Completed]
    *   Refactor the simulation engine to use the new `DeliveryService`.
    *   Remove the `SingleRunnerDeliveryService` and `MultiRunnerDeliveryService` classes from `golfsim/simulation/services.py`.

---

### Phase 3: Decouple Configuration [Completed]

**Goal:** Make the simulation more flexible and easier to configure for different scenarios.

**Issue:** Core simulation parameters are hardcoded in `simulation_config.json`, making it difficult to run experiments.

**Steps:**

1.  **Introduce Command-Line Arguments:** [Completed]
    *   Modify the main simulation scripts (e.g., `scripts/sim/run_unified_simulation.py`) to accept key parameters as command-line arguments (e.g., `--runner-speed`, `--prep-time`).
    *   Use the values in `simulation_config.json` as default values for these arguments.

2.  **Update Simulation Logic:** [Completed]
    *   Refactor the simulation to use the configuration values passed in from the command line.

3.  **Document New Configuration Options:** [Completed]
    *   Update the `README.md` to document the new command-line arguments and how to use them.

---

### Phase 4: Decompose Monolithic `services.py` [Completed]

**Goal:** Improve code organization and maintainability by breaking down the oversized `services.py` file.

**Issue:** The `golfsim/simulation/services.py` file has become a "god object" with too many responsibilities.

**Steps:**

1.  **Create New Modules:** [Completed]
    *   `golfsim/simulation/beverage_cart_service.py`: For the `BeverageCartService` class.
    *   `golfsim/simulation/order_generation.py`: For the `simulate_golfer_orders` function.

2.  **Move Code:** [Completed]
    *   Migrate the relevant classes and functions from `services.py` to the new modules.

3.  **Refactor Imports:** [Completed]
    *   Update all import statements across the project to reflect the new file structure.
    *   The `services.py` file can either be removed or repurposed for high-level service orchestration.

---

### Phase 5: Enhance Test Coverage [Completed]

**Goal:** Ensure the reliability and stability of the simulation by improving the testing strategy.

**Issue:** The project has minimal test coverage, with no tests for the multi-runner service or for failure scenarios.

**Steps:**

1.  **Create New Test Files:** [Completed]
    *   `tests/unit/test_delivery_service.py`: For unit tests of the new `DeliveryService`.
    *   `tests/integration/test_simulation_scenarios.py`: For end-to-end tests of different simulation scenarios.

2.  **Write Comprehensive Tests:** [Completed]
    *   Add tests for both single-runner and multi-runner configurations.
    *   Include tests for failure cases (e.g., order timeouts, invalid configurations) and edge cases (e.g., zero runners, orders placed at the end of the day).

3.  **Organize Test Suite:** [Completed]
    *   Structure the `tests/` directory to separate unit and integration tests.

4.  **Implement CI:**
    *   Set up a continuous integration pipeline (e.g., using GitHub Actions) to automatically run the test suite on every code change.
