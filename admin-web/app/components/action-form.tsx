"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { useFormState, useFormStatus } from "react-dom";

import { EMPTY_FORM_STATE, type FormState } from "../lib/form-state";

type ActionFormProps = {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  children: ReactNode;
  className?: string;
  resetOnSuccess?: boolean;
};

export function ActionForm({
  action,
  children,
  className,
  resetOnSuccess = false
}: ActionFormProps) {
  const formRef = useRef<HTMLFormElement>(null);
  const lastStatusRef = useRef<FormState["status"]>(EMPTY_FORM_STATE.status);
  const [state, formAction] = useFormState(action, EMPTY_FORM_STATE);

  useEffect(() => {
    if (resetOnSuccess && state.status === "success" && lastStatusRef.current !== "success") {
      formRef.current?.reset();
    }

    lastStatusRef.current = state.status;
  }, [resetOnSuccess, state.status]);

  return (
    <form ref={formRef} action={formAction}>
      <ActionFormBody className={className} state={state}>
        {children}
      </ActionFormBody>
    </form>
  );
}

function ActionFormBody({
  className,
  children,
  state
}: {
  className?: string;
  children: ReactNode;
  state: FormState;
}) {
  const { pending } = useFormStatus();

  return (
    <fieldset className={className ? `form-fieldset ${className}` : "form-fieldset"} disabled={pending}>
      {children}
      {state.message ? (
        <p
          className={`form-feedback ${
            state.status === "error" ? "form-feedback-error" : "form-feedback-success"
          }`}
          aria-live="polite"
        >
          {state.message}
        </p>
      ) : null}
    </fieldset>
  );
}
