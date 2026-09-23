import { formatModelLabel } from "@/components/workspace/command-center/model-label";
import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";

import { getBackendBaseURL } from "../config";
import { isStaticWebsiteOnly } from "../static-mode";

import type { Model, ModelsResponse } from "./types";

/**
 * Every model surface reads names through here. The configured display name
 * is shown as written (config owns the wording); a model without one gets a
 * presentable name instead of its routing slug.
 */
export function presentModel(model: Model): Model {
  return model.display_name?.trim()
    ? model
    : { ...model, display_name: formatModelLabel(model.name) };
}

const STATIC_MODELS_RESPONSE: ModelsResponse = {
  models: [],
  token_usage: { enabled: false },
};

export async function loadModels(): Promise<ModelsResponse> {
  if (isStaticWebsiteOnly()) {
    return STATIC_MODELS_RESPONSE;
  }

  const res = await fetch(`${getBackendBaseURL()}/api/models`);
  if (!res.ok) {
    await throwGatewayApiError(
      res,
      `Failed to load models: ${res.status} ${res.statusText}`.trim(),
    );
  }
  const data = (await res.json()) as Partial<ModelsResponse>;
  return {
    models: (data.models ?? []).map(presentModel),
    token_usage: data.token_usage ?? { enabled: false },
  };
}
