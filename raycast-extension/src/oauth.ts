import { OAuth } from "@raycast/api";
import { OAuthService } from "@raycast/utils";

const AUTHORIZE_URL =
  "https://oauth.raycast.com/v1/authorize/CuOnsEA5871f6X46g0NuPzvVvCfXr45HbimqXk-No6DQhwWW6tA8t7qD94048ICd23m4HjqPS-Pi0eZpzfSPUqm2QRTsUjFcWgSBTQNAYSnkBji5MNQiovY_wiubTJj-_mQ";
const TOKEN_URL =
  "https://oauth.raycast.com/v1/token/TR2yXhB8uHsszBLznIuAhfBpyX4YTiw_ByT9ReQCl7ujUDcusy7Y_PBtU_7-XGoSRgMUTAUvM4XbiRaMr6xutJS0C-qqPXjXNKTWfbriOtXJtNwary7AWsGoU9_NMmuhHmk";
const REFRESH_URL =
  "https://oauth.raycast.com/v1/refresh-token/sbGDwp2lnfz3l-yQfZ5dGXYinlKeROP3FI-czhhKNiNwHTLyXwBykj280WtyrK8fLJA1kgywSICPvT_BM1v_VCatailqbFAMrrV-y1LFWFxxdnhvFZUvpZ_13xT0-IsR1-c";

const client = new OAuth.PKCEClient({
  redirectMethod: OAuth.RedirectMethod.Web,
  providerName: "Discord",
  providerIcon: "command-icon.png",
  description: "Connect your Discord account to manage deadlines.",
});

export const provider = new OAuthService({
  client,
  clientId: "1484564963996598413",
  scope: "identify",
  authorizeUrl: AUTHORIZE_URL,
  tokenUrl: TOKEN_URL,
  refreshTokenUrl: REFRESH_URL,
});

export const authorize = () => provider.authorize();

