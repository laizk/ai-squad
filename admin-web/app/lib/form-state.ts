export type FormState = {
  status: "idle" | "error" | "success";
  message: string | null;
};

export const EMPTY_FORM_STATE: FormState = {
  status: "idle",
  message: null
};

export function formSuccess(message: string): FormState {
  return {
    status: "success",
    message
  };
}

export function formError(message: string): FormState {
  return {
    status: "error",
    message
  };
}

export function formErrorFromUnknown(error: unknown, fallback = "Request failed."): FormState {
  if (error instanceof Error && error.message.trim()) {
    return formError(error.message);
  }

  return formError(fallback);
}
