"""Public, actionable errors that can be safely recorded in run reports."""


class TestPilotError(Exception):
    """Base for expected application failures."""


class ConfigurationError(TestPilotError):
    pass


class ProjectAnalysisError(TestPilotError):
    pass


class DependencyError(TestPilotError):
    pass


class LLMError(TestPilotError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMOutputValidationError(LLMError):
    pass


class LLMOutputTruncatedError(LLMOutputValidationError):
    """The provider stopped before producing a complete structured response."""


class TestExecutionError(TestPilotError):
    pass


class DockerUnavailableError(TestExecutionError):
    pass


class CoverageError(TestPilotError):
    pass


class WorkflowError(TestPilotError):
    pass
