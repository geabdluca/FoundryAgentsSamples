"""
setup_apim_api.py — APIM + Foundry Connection Bootstrap
=========================================================
Run this ONCE to:
  1. Create a Contoso IT Helpdesk mock API on your Azure API Management instance,
     complete with a return-response policy (no real backend required).
  2. Create an APIM product and subscription, then retrieve the subscription key.
  3. Register a CustomKeys project connection in your Foundry project so the agent
     can inject the APIM subscription key at runtime via OpenApiTool connection auth.

Steps 1 and 3 are individually gated by config flags:
  create_apim_api          = true/false
  create_foundry_connection = true/false

Both operations are idempotent — safe to re-run.

Authentication: DefaultAzureCredential (az login for local dev, Managed Identity in prod)
Configuration:  config.json in the same directory as this script

Prerequisites:
  - Azure API Management instance (Consumption, Developer, or Standard tier)
  - Your identity needs "API Management Service Contributor" on the APIM resource
  - Your identity needs "Contributor" (or connections/write) on the Foundry project
    to create the project connection
  - pip install -r requirements.txt
  - az login when running locally

After running this script, run agent_openapi_apim.py to create the agent and query it.
"""

import json
import sys
from pathlib import Path

import requests
from azure.identity import DefaultAzureCredential
from azure.mgmt.apimanagement import ApiManagementClient
from azure.mgmt.apimanagement.models import (
    ApiCreateOrUpdateParameter,
    PolicyContract,
    ProductContract,
    SubscriptionCreateParameters,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.json"
SPEC_PATH = Path(__file__).parent / "openapi_spec.json"

ARM_API_VERSION = "2025-10-01-preview"

# Mock policy: always returns a realistic-looking Contoso IT helpdesk answer.
# Replace this with a real backend URL + policy once you have an actual agent
# service behind APIM.
MOCK_POLICY_XML = """\
<policies>
  <inbound>
    <base />
  </inbound>
  <backend>
    <return-response>
      <set-status code="200" reason="OK" />
      <set-header name="Content-Type" exists-action="override">
        <value>application/json</value>
      </set-header>
      <set-body><![CDATA[{
  "answer": "There are currently 3 open P2 incidents. The most recent is INC-00234 regarding VPN connectivity in the Seattle office, opened 2 hours ago and assigned to the Network Operations team with an estimated resolution of 4 hours. Would you like details on any specific incident?"
}]]></set-body>
    </return-response>
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>"""


def load_config(path: Path) -> dict:
    """Load and validate configuration from config.json."""
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    base_required = [
        "apim_service_name",
        "apim_api_path",
        "apim_connection_name",
    ]
    apim_required = [
        "azure_subscription_id",
        "apim_resource_group",
        "apim_product_id",
        "apim_sub_name",
    ]
    conn_required = [
        "project_resource_id",
    ]

    check = list(base_required)
    if cfg.get("create_apim_api", False):
        check.extend(apim_required)
    if cfg.get("create_foundry_connection", False):
        check.extend(conn_required)

    missing = [k for k in check if not cfg.get(k) or str(cfg[k]).startswith("<")]
    if missing:
        print(
            "ERROR: The following config.json values are missing or still contain "
            f"placeholder text:\n  {', '.join(missing)}\n"
            "Please fill in config.json before running this script."
        )
        sys.exit(1)

    return cfg


# ---------------------------------------------------------------------------
# Step 1: Create APIM API with mock policy
# ---------------------------------------------------------------------------

def create_apim_api(
    credential: DefaultAzureCredential,
    azure_subscription_id: str,
    resource_group: str,
    service_name: str,
    api_path: str,
    product_id: str,
    sub_name: str,
) -> str:
    """
    Create the Contoso IT Helpdesk API in APIM from openapi_spec.json, apply a
    return-response mock policy, create a product and subscription, and return the
    primary subscription key.

    Returns the primary subscription key string.
    """
    apim = ApiManagementClient(credential, azure_subscription_id)
    api_id = "contoso-itdesk-agent"

    # Load and patch spec — set the gateway base URL in servers[0]
    with open(SPEC_PATH, encoding="utf-8") as f:
        spec = json.load(f)
    # APIM default gateway URLs are always lowercase regardless of the resource name casing
    gateway_url = f"https://{service_name.lower()}.azure-api.net/{api_path}"
    spec["servers"][0]["url"] = gateway_url

    # Create (or update) the API by importing the OpenAPI spec
    print(f"  Creating APIM API '{api_id}' at path '/{api_path}'...")
    apim.api.begin_create_or_update(
        resource_group_name=resource_group,
        service_name=service_name,
        api_id=api_id,
        parameters=ApiCreateOrUpdateParameter(
            display_name="Contoso IT Helpdesk Agent",
            description=(
                "Natural-language interface to the Contoso IT Helpdesk. "
                "Returns answers about incidents, service requests, and IT policies."
            ),
            service_url=gateway_url,   # ignored when mock policy is active
            path=api_path,
            protocols=["https"],
            format="openapi+json",
            value=json.dumps(spec),
        ),
    ).result()
    print(f"  [OK] API '{api_id}' created/updated.")

    # Apply mock return-response policy at the API level
    print("  Applying mock return-response policy...")
    apim.api_policy.create_or_update(
        resource_group_name=resource_group,
        service_name=service_name,
        api_id=api_id,
        policy_id="policy",
        parameters=PolicyContract(
            format="xml",
            value=MOCK_POLICY_XML,
        ),
    )
    print("  [OK] Mock policy applied.")

    # Create product (groups APIs and controls subscription requirements)
    print(f"  Creating product '{product_id}'...")
    apim.product.create_or_update(
        resource_group_name=resource_group,
        service_name=service_name,
        product_id=product_id,
        parameters=ProductContract(
            display_name="Contoso IT Helpdesk",
            description="Access to the Contoso IT Helpdesk Agent API",
            subscription_required=True,
            state="published",
        ),
    )
    print(f"  [OK] Product '{product_id}' created/updated.")

    # Link API to product
    apim.product_api.create_or_update(
        resource_group_name=resource_group,
        service_name=service_name,
        product_id=product_id,
        api_id=api_id,
    )
    print(f"  [OK] API linked to product '{product_id}'.")

    # Create subscription
    full_product_scope = (
        f"/subscriptions/{azure_subscription_id}"
        f"/resourceGroups/{resource_group}"
        f"/providers/Microsoft.ApiManagement/service/{service_name}"
        f"/products/{product_id}"
    )
    print(f"  Creating subscription '{sub_name}'...")
    apim.subscription.create_or_update(
        resource_group_name=resource_group,
        service_name=service_name,
        sid=sub_name,
        parameters=SubscriptionCreateParameters(
            display_name="Contoso IT Helpdesk Subscription",
            scope=full_product_scope,
        ),
    )
    print(f"  [OK] Subscription '{sub_name}' created/updated.")

    # Retrieve subscription key
    secrets = apim.subscription.list_secrets(
        resource_group_name=resource_group,
        service_name=service_name,
        sid=sub_name,
    )
    primary_key = secrets.primary_key
    print("  [OK] Subscription key retrieved.")

    return primary_key


# ---------------------------------------------------------------------------
# Step 2: Create Foundry CustomKeys connection
# ---------------------------------------------------------------------------

def create_foundry_connection(
    credential: DefaultAzureCredential,
    project_resource_id: str,
    connection_name: str,
    apim_base_url: str,
    subscription_key: str,
) -> None:
    """
    Create (or update) a CustomKeys project connection in the Foundry project.

    The connection stores the APIM subscription key under the header name
    'Ocp-Apim-Subscription-Key', which maps directly to the security scheme
    defined in openapi_spec.json. The OpenApiTool runtime injects this header
    automatically when the agent calls the APIM endpoint.

    Uses PUT {ARM}/{project_resource_id}/connections/{name} — idempotent upsert.
    """
    token = credential.get_token("https://management.azure.com/.default").token
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = (
        f"https://management.azure.com{project_resource_id}"
        f"/connections/{connection_name}?api-version={ARM_API_VERSION}"
    )
    payload = {
        "name": connection_name,
        "type": "Microsoft.MachineLearningServices/workspaces/connections",
        "properties": {
            "authType": "CustomKeys",
            "category": "CustomKeys",
            "target": apim_base_url,
            "isSharedToAll": True,
            "credentials": {
                "keys": {
                    # Key name must match the header name in the OpenAPI security scheme
                    "Ocp-Apim-Subscription-Key": subscription_key
                }
            },
        },
    }
    response = requests.put(url, headers=headers, json=payload, timeout=60)
    if not response.ok:
        print(f"  Response body: {response.text}")
    response.raise_for_status()
    print(f"  [OK] Foundry connection '{connection_name}' created/updated.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config(CONFIG_PATH)

    service_name = cfg["apim_service_name"]
    api_path = cfg["apim_api_path"]
    connection_name = cfg["apim_connection_name"]
    apim_base_url = f"https://{service_name.lower()}.azure-api.net/{api_path}"

    credential = DefaultAzureCredential()
    subscription_key: str | None = None

    # -- Step 1: Create APIM API --
    if cfg.get("create_apim_api", False):
        print("\n=== Step 1: Creating APIM API ===")
        subscription_key = create_apim_api(
            credential=credential,
            azure_subscription_id=cfg["azure_subscription_id"],
            resource_group=cfg["apim_resource_group"],
            service_name=service_name,
            api_path=api_path,
            product_id=cfg["apim_product_id"],
            sub_name=cfg["apim_sub_name"],
        )
        print(f"\nAPIM endpoint ready: POST {apim_base_url}/query")
    else:
        print("\n=== Step 1: Skipped (create_apim_api=false) ===")
        print(f"  Assuming API already exists at: POST {apim_base_url}/query")

    # -- Step 2: Create Foundry connection --
    if cfg.get("create_foundry_connection", False):
        print("\n=== Step 2: Creating Foundry CustomKeys connection ===")
        if subscription_key is None:
            # APIM API already existed — prompt user for the key
            subscription_key = input(
                "  Enter the APIM subscription key for the Contoso IT Helpdesk API: "
            ).strip()
            if not subscription_key:
                print("ERROR: Subscription key is required to create the Foundry connection.")
                sys.exit(1)
        create_foundry_connection(
            credential=credential,
            project_resource_id=cfg["project_resource_id"],
            connection_name=connection_name,
            apim_base_url=apim_base_url,
            subscription_key=subscription_key,
        )
    else:
        print("\n=== Step 2: Skipped (create_foundry_connection=false) ===")
        print(f"  Using existing connection: '{connection_name}'.")

    print("\n=== Setup complete ===")
    print(f"  APIM endpoint : POST {apim_base_url}/query")
    print(f"  Connection    : {connection_name}")
    print("\nNext step: run agent_openapi_apim.py to create the agent and run a query.")


if __name__ == "__main__":
    main()
