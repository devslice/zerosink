export default {
  async fetch(request, env, ctx) {
    // Enable CORS
    const headers = {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type"
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers });
    }

    const url = new URL(request.url);
    if (url.pathname !== "/verify") {
      return new Response(JSON.stringify({ error: "Not Found" }), {
        status: 404,
        headers
      });
    }

    const subId = url.searchParams.get("sub_id");
    if (!subId || !subId.startsWith("sub_")) {
      return new Response(JSON.stringify({ activated: false, error: "Invalid subscription ID format." }), {
        status: 400,
        headers
      });
    }

    if (!env.STRIPE_SECRET_KEY) {
      return new Response(JSON.stringify({ activated: false, error: "Stripe API key not configured on licensing server." }), {
        status: 500,
        headers
      });
    }

    const stripeUrl = `https://api.stripe.com/v1/subscriptions/${subId}`;
    
    try {
      const response = await fetch(stripeUrl, {
        method: "GET",
        headers: {
          "Authorization": `Bearer ${env.STRIPE_SECRET_KEY}`,
          "Accept": "application/json"
        }
      });

      if (!response.ok) {
        const errData = await response.json();
        const errMsg = errData.error?.message || `Stripe API error: ${response.status}`;
        return new Response(JSON.stringify({ activated: false, error: errMsg }), {
          status: response.status,
          headers
        });
      }

      const data = await response.json();
      const status = data.status;

      if (status !== "active" && status !== "trialing") {
        return new Response(JSON.stringify({ activated: false, error: `Subscription is not active (Status: ${status})` }), {
          status: 200,
          headers
        });
      }

      const items = data.items?.data || [];
      let hasMatchingPrice = false;
      for (const item of items) {
        if (item.price?.id === env.STRIPE_PRICE_ID) {
          hasMatchingPrice = true;
          break;
        }
      }

      if (!hasMatchingPrice) {
        return new Response(JSON.stringify({ activated: false, error: `Subscription does not contain expected product price.` }), {
          status: 200,
          headers
        });
      }

      const expiresAt = data.current_period_end 
        ? new Date(data.current_period_end * 1000).toISOString()
        : new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString();

      return new Response(JSON.stringify({
        activated: true,
        status: "active",
        expires_at: expiresAt
      }), {
        status: 200,
        headers
      });

    } catch (e) {
      return new Response(JSON.stringify({ activated: false, error: `Connection failed: ${e.message}` }), {
        status: 500,
        headers
      });
    }
  }
};
