"""Public error codes never contain model, client, credential, or source text."""


class WorkflowError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class WorkflowInputError(WorkflowError):
    pass


class WorkflowOutputError(WorkflowError):
    pass


class WorkflowReviewError(WorkflowError):
    pass


class WorkflowResumeError(WorkflowError):
    pass


class WorkflowCallbackError(WorkflowError):
    pass
