import { OAuth } from "@raycast/api";
import { OAuthService } from "@raycast/utils";
import { getPreferenceValues } from "@raycast/api";

// Discord supports PKCE natively, so we use its real endpoints directly.
// No Raycast proxy (oauth.raycast.com) is needed.
//
// Redirect URI to register in the Discord Developer Portal (OAuth2 → Redirects):
//   https://raycast.com/redirect?packageName=Extension
//
// Discord's token endpoint requires application/x-www-form-urlencoded bodies
// (not JSON), hence bodyEncoding: "url-encoded".

interface Preferences {
  apiBaseUrl: string;
  discordClientId: string;
}

const client = new OAuth.PKCEClient({
  redirectMethod: OAuth.RedirectMethod.Web,
  providerName: "Discord",
  providerIcon: "command-icon.png",
  description: "Connect your Discord account to manage deadlines.",
});

// Lazily initialised so that discordClientId is read from preferences at
// runtime rather than hardcoded at build time.
let _provider: OAuthService | null = null;

function getProvider(): OAuthService {
  if (!_provider) {
    const { discordClientId } = getPreferenceValues<Preferences>();
    _provider = new OAuthService({
      client,
      clientId: discordClientId,
      scope: "identify",
      authorizeUrl: "https://discord.com/oauth2/authorize",
      tokenUrl: "https://discord.com/api/oauth2/token",
      refreshTokenUrl: "https://discord.com/api/oauth2/token",
      bodyEncoding: "url-encoded",
    });
  }
  return _provider;
}

export const authorize = () => getProvider().authorize();
