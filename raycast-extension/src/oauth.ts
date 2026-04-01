import { OAuth } from "@raycast/api";
import { OAuthService } from "@raycast/utils";

// Discord supports PKCE natively, so we use its real endpoints directly.
// No Raycast proxy (oauth.raycast.com) is needed.
//
// Redirect URI to register in the Discord Developer Portal (OAuth2 → Redirects):
//   https://raycast.com/redirect?packageName=Extension
//
// Discord's token endpoint requires application/x-www-form-urlencoded bodies
// (not JSON), hence bodyEncoding: "url-encoded".

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
  authorizeUrl: "https://discord.com/oauth2/authorize",
  tokenUrl: "https://discord.com/api/oauth2/token",
  refreshTokenUrl: "https://discord.com/api/oauth2/token",
  bodyEncoding: "url-encoded",
});

export const authorize = () => provider.authorize();
