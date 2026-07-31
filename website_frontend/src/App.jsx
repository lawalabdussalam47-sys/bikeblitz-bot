import React, { useState, useMemo, useEffect } from "react";
import logo from "./assets/IMG_7232.png";

// Live backend URL — update this if you ever redeploy the backend elsewhere.
const API_BASE = "https://bikeblitz-website.onrender.com";

// ---------- Pricing data (mirrors bikeblitz_bot.py exactly) ----------
const ZONES = [
  { id: "z1", name: "Zone 1 — On Campus", desc: "Anywhere within FUNAAB campus", prices: { Light: 300, Medium: 500, Heavy: 700 } },
  { id: "z2", name: "Zone 2 — Near Off Campus", desc: "Harmony, Accord, Zoo, Agbede, Kofesu", prices: { Light: 500, Medium: 700, Heavy: 900 } },
  { id: "z3", name: "Zone 3 — Mid Off Campus", desc: "Labuta, Isolu-Cele, Isolu-FUNIS, Camp", prices: { Light: 700, Medium: 900, Heavy: 1100 } },
  { id: "z4", name: "Zone 4 — Far Off Campus", desc: "Town", prices: { Light: 1200, Medium: 1400, Heavy: 1600 } },
];
const ERRAND_FEES = { "Simple Errand / Food Order": 100, "Complex Errand / Bulk Shopping": 250 };
const EXPRESS_SURCHARGE = 300;
const DISTANCE_MODIFIER = 200;
const WEIGHTS = ["Light", "Medium", "Heavy"];

const naira = (n) => `₦${n.toLocaleString()}`;

function RouteDot({ active, done, label, index }) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex flex-col items-center">
        <div
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 font-mono text-xs font-bold transition-colors ${
            done
              ? "border-lime-400 bg-lime-400 text-neutral-900"
              : active
              ? "border-lime-400 text-lime-400"
              : "border-neutral-600 text-neutral-500"
          }`}
        >
          {index}
        </div>
        <div className={`mt-1 w-px flex-1 ${done ? "bg-lime-400" : "bg-neutral-700"}`} style={{ minHeight: 28 }} />
      </div>
      <div className={`pb-7 pt-0.5 text-sm ${active ? "text-neutral-100" : "text-neutral-500"}`}>{label}</div>
    </div>
  );
}

function TrackOrder({ reference }) {
  const [order, setOrder] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/orders/${reference}`);
        const data = await res.json();
        if (cancelled) return;
        if (!res.ok) {
          setError(data.error || "Couldn't find that order.");
          return;
        }
        setOrder(data);
      } catch (err) {
        if (!cancelled) setError("Couldn't reach the server.");
      }
    };
    poll();
    const interval = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [reference]);

  const statusSteps = ["Pending Payment", "Paid", "Claimed", "Delivered"];
  const currentIndex = order ? statusSteps.indexOf(order.status) : -1;

  return (
    <div className="min-h-screen w-full bg-neutral-900 px-5 py-16 text-neutral-100">
      <div className="mx-auto max-w-md rounded-2xl border border-neutral-800 bg-neutral-800/40 p-8">
        <h1 className="text-xl font-black">Tracking your order</h1>
        <p className="mt-1 font-mono text-xs text-neutral-500">{reference}</p>

        {error && <div className="mt-6 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-300">{error}</div>}

        {order && (
          <>
            <div className="mt-6 space-y-3">
              {statusSteps.map((s, i) => (
                <div key={s} className="flex items-center gap-3">
                  <div
                    className={`h-2.5 w-2.5 rounded-full ${
                      i <= currentIndex ? "bg-lime-400" : "bg-neutral-700"
                    }`}
                  />
                  <span className={i <= currentIndex ? "text-neutral-100" : "text-neutral-600"}>{s}</span>
                </div>
              ))}
            </div>
            {order.riderName && (
              <p className="mt-5 text-sm text-neutral-400">
                Rider assigned: <span className="text-neutral-100">{order.riderName}</span>
              </p>
            )}
            <p className="mt-2 text-sm text-neutral-500">
              {order.zone} — {naira(Number(order.total || 0))}
            </p>
          </>
        )}

        {!order && !error && <p className="mt-6 text-sm text-neutral-500">Loading…</p>}

        <p className="mt-8 text-xs text-neutral-600">This page refreshes automatically every few seconds.</p>
      </div>
    </div>
  );
}

export default function BikeBlitzSite() {
  const params = new URLSearchParams(typeof window !== "undefined" ? window.location.search : "");
  const trackingReference = params.get("reference");

  if (trackingReference) {
    return <TrackOrder reference={trackingReference} />;
  }

  return <OrderFlow />;
}

function OrderFlow() {
  const [step, setStep] = useState(0); // 0 service, 1 zone, 2 details, 3 review, 4 pay
  const [service, setService] = useState(null); // "B2B" | "B2C"
  const [zoneId, setZoneId] = useState(null);
  const [weight, setWeight] = useState(null);
  const [errandType, setErrandType] = useState(null);
  const [errandItems, setErrandItems] = useState("");
  const [express, setExpress] = useState(false);
  const [farBusstop, setFarBusstop] = useState(false);
  const [location, setLocation] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [paying, setPaying] = useState(false);
  const [paid, setPaid] = useState(false);
  const [checkoutError, setCheckoutError] = useState("");

  const zone = ZONES.find((z) => z.id === zoneId);

  const pricing = useMemo(() => {
    if (!zone) return null;
    const distanceAdd = farBusstop ? DISTANCE_MODIFIER : 0;
    const expressAdd = express ? EXPRESS_SURCHARGE : 0;
    if (service === "B2B") {
      const base = weight ? zone.prices[weight] : 0;
      return { base, distanceAdd, expressAdd, total: base + distanceAdd + expressAdd, label: "Delivery charge" };
    }
    if (service === "B2C") {
      const base = zone.prices.Light;
      const fee = errandType ? ERRAND_FEES[errandType] : 0;
      return { base, fee, distanceAdd, expressAdd, total: base + fee + distanceAdd + expressAdd, label: "Delivery charge" };
    }
    return null;
  }, [zone, service, weight, errandType, express, farBusstop]);

  const canAdvance = () => {
    if (step === 0) return !!service;
    if (step === 1) return !!zoneId && (service === "B2C" || !!weight) && (service === "B2B" || !!errandType);
    if (step === 2)
      return (
        location.trim().length > 3 &&
        (service === "B2C" ? errandItems.trim().length > 3 : true) &&
        customerName.trim().length > 1 &&
        phone.trim().length >= 7 &&
        /\S+@\S+\.\S+/.test(email)
      );
    return true;
  };

  const reset = () => {
    setStep(0);
    setService(null);
    setZoneId(null);
    setWeight(null);
    setErrandType(null);
    setErrandItems("");
    setExpress(false);
    setFarBusstop(false);
    setLocation("");
    setCustomerName("");
    setPhone("");
    setEmail("");
    setPaying(false);
    setPaid(false);
    setCheckoutError("");
  };

  const steps = ["Service", "Zone & type", "Details", "Review", "Pay"];

  return (
    <div className="min-h-screen w-full bg-neutral-900 text-neutral-100" style={{ fontFamily: "'Helvetica Neue', Arial, sans-serif" }}>
      {/* Header */}
      <header className="border-b border-neutral-800 bg-neutral-900/95 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-4">
          <div className="flex items-center gap-2">
            <img
              src={logo}
              alt="BikeBlitz"
              className="h-9 w-9 rounded-lg"
            />
            <span className="text-lg font-black tracking-tight">BikeBlitz</span>
          </div>
          <div className="hidden items-center gap-6 text-sm text-neutral-400 sm:flex">
            <span>Pricing</span>
            <span>Zones</span>
            <span>Ride for us</span>
          </div>
          <div className="rounded-full border border-neutral-700 px-3 py-1 font-mono text-xs text-neutral-400">FUNAAB · Abeokuta</div>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden border-b border-neutral-800 px-5 py-14">
        <div
          className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full opacity-20 blur-3xl"
          style={{ background: "#8A3820" }}
        />
        <div className="mx-auto max-w-5xl">
          <div className="mb-3 inline-block rounded-full border px-3 py-1 font-mono text-xs" style={{ borderColor: "#8A3820", color: "#c9724f" }}>
            Same-day · 9am–9pm · cutoff 8pm
          </div>
          <h1 className="max-w-2xl text-4xl font-black leading-[1.05] tracking-tight sm:text-6xl">
            Fast. Reliable.
            <br />
            <span style={{ color: "#C4F135" }}>Zero silence.</span>
          </h1>
          <p className="mt-4 max-w-md text-neutral-400">
            Campus delivery and errands, run by FUNAAB students on bikes who know every gate and shortcut.
            Place an order, pay, track your rider — all in one page.
          </p>
        </div>
      </section>

      {/* Order flow */}
      <section className="mx-auto grid max-w-5xl grid-cols-1 gap-8 px-5 py-12 md:grid-cols-[200px_1fr]">
        {/* Route line */}
        <div className="hidden md:block">
          {steps.map((label, i) => (
            <RouteDot key={label} index={i + 1} label={label} active={step === i} done={step > i} />
          ))}
        </div>

        {/* Card */}
        <div className="rounded-2xl border border-neutral-800 bg-neutral-850 bg-neutral-800/40 p-6 sm:p-8">
          <div className="mb-6 flex items-center justify-between md:hidden">
            <span className="font-mono text-xs text-neutral-500">
              Step {step + 1} of {steps.length}
            </span>
            <span className="text-sm font-semibold">{steps[step]}</span>
          </div>

          {/* Step 0: service */}
          {step === 0 && (
            <div>
              <h2 className="text-xl font-bold">What do you need delivered?</h2>
              <p className="mt-1 text-sm text-neutral-500">Pick one to get a live price quote.</p>
              <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <button
                  onClick={() => setService("B2B")}
                  className={`rounded-xl border p-5 text-left transition-colors ${
                    service === "B2B" ? "border-lime-400 bg-lime-400/10" : "border-neutral-700 hover:border-neutral-500"
                  }`}
                >
                  <div className="text-2xl">📦</div>
                  <div className="mt-2 font-semibold">Send a Package</div>
                  <div className="mt-1 text-xs text-neutral-500">Documents, parcels, anything that needs a ride across campus.</div>
                </button>
                <button
                  onClick={() => setService("B2C")}
                  className={`rounded-xl border p-5 text-left transition-colors ${
                    service === "B2C" ? "border-lime-400 bg-lime-400/10" : "border-neutral-700 hover:border-neutral-500"
                  }`}
                >
                  <div className="text-2xl">🛒</div>
                  <div className="mt-2 font-semibold">Errand / Food / Market</div>
                  <div className="mt-1 text-xs text-neutral-500">We buy and bring it — food, groceries, market runs.</div>
                </button>
              </div>
              <label className="mt-6 flex items-center gap-2 text-sm text-neutral-400">
                <input type="checkbox" checked={express} onChange={(e) => setExpress(e.target.checked)} className="accent-lime-400" />
                Express delivery (+{naira(EXPRESS_SURCHARGE)}, priority handling)
              </label>
            </div>
          )}

          {/* Step 1: zone + type */}
          {step === 1 && (
            <div>
              <h2 className="text-xl font-bold">Where's this going?</h2>
              <div className="mt-5 space-y-2">
                {ZONES.map((z) => (
                  <button
                    key={z.id}
                    onClick={() => setZoneId(z.id)}
                    className={`flex w-full items-center justify-between rounded-lg border px-4 py-3 text-left transition-colors ${
                      zoneId === z.id ? "border-lime-400 bg-lime-400/10" : "border-neutral-700 hover:border-neutral-500"
                    }`}
                  >
                    <div>
                      <div className="text-sm font-semibold">{z.name}</div>
                      <div className="text-xs text-neutral-500">{z.desc}</div>
                    </div>
                    <div className="font-mono text-xs text-neutral-400">from {naira(Object.values(z.prices)[0])}</div>
                  </button>
                ))}
              </div>

              {service === "B2B" && (
                <div className="mt-6">
                  <div className="mb-2 text-sm font-semibold">How heavy is it?</div>
                  <div className="flex flex-wrap gap-2">
                    {WEIGHTS.map((w) => (
                      <button
                        key={w}
                        onClick={() => setWeight(w)}
                        className={`rounded-full border px-4 py-1.5 text-sm transition-colors ${
                          weight === w ? "border-lime-400 bg-lime-400/10" : "border-neutral-700 hover:border-neutral-500"
                        }`}
                      >
                        {w}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {service === "B2C" && (
                <div className="mt-6">
                  <div className="mb-2 text-sm font-semibold">What kind of errand?</div>
                  <div className="flex flex-wrap gap-2">
                    {Object.keys(ERRAND_FEES).map((t) => (
                      <button
                        key={t}
                        onClick={() => setErrandType(t)}
                        className={`rounded-full border px-4 py-1.5 text-sm transition-colors ${
                          errandType === t ? "border-lime-400 bg-lime-400/10" : "border-neutral-700 hover:border-neutral-500"
                        }`}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Step 2: details */}
          {step === 2 && (
            <div>
              <h2 className="text-xl font-bold">A few more details</h2>
              {service === "B2C" && (
                <div className="mt-5">
                  <label className="mb-1 block text-sm font-semibold">What exactly do you need?</label>
                  <textarea
                    value={errandItems}
                    onChange={(e) => setErrandItems(e.target.value)}
                    placeholder="2 loaves of bread, a carton of eggs, from Mama Nkechi's shop near Zoo gate"
                    className="w-full rounded-lg border border-neutral-700 bg-neutral-900 p-3 text-sm outline-none focus:border-lime-400"
                    rows={3}
                  />
                </div>
              )}
              <div className="mt-5">
                <label className="mb-1 block text-sm font-semibold">Exact location</label>
                <input
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="Alpha Hostel, Room 14, behind the FUNAAB clinic"
                  className="w-full rounded-lg border border-neutral-700 bg-neutral-900 p-3 text-sm outline-none focus:border-lime-400"
                />
              </div>
              <label className="mt-4 flex items-center gap-2 text-sm text-neutral-400">
                <input type="checkbox" checked={farBusstop} onChange={(e) => setFarBusstop(e.target.checked)} className="accent-lime-400" />
                Far from the main bus stop (+{naira(DISTANCE_MODIFIER)})
              </label>

              <div className="mt-6 grid grid-cols-1 gap-4 border-t border-neutral-800 pt-5 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-sm font-semibold">Your name</label>
                  <input
                    value={customerName}
                    onChange={(e) => setCustomerName(e.target.value)}
                    placeholder="Full name"
                    className="w-full rounded-lg border border-neutral-700 bg-neutral-900 p-3 text-sm outline-none focus:border-lime-400"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-semibold">Phone (WhatsApp)</label>
                  <input
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="0801 234 5678"
                    className="w-full rounded-lg border border-neutral-700 bg-neutral-900 p-3 text-sm outline-none focus:border-lime-400"
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="mb-1 block text-sm font-semibold">Email (for your payment receipt)</label>
                  <input
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full rounded-lg border border-neutral-700 bg-neutral-900 p-3 text-sm outline-none focus:border-lime-400"
                  />
                </div>
              </div>
            </div>
          )}

          {/* Step 3: review */}
          {step === 3 && pricing && (
            <div>
              <h2 className="text-xl font-bold">Review your order</h2>
              <div className="mt-5 divide-y divide-neutral-800 rounded-lg border border-neutral-800 font-mono text-sm">
                <Row label="Service" value={service === "B2B" ? "Package delivery" : errandType} />
                {service === "B2C" && <Row label="Items" value={errandItems} />}
                <Row label="Zone" value={zone.name} />
                <Row label="Location" value={location} />
                <Row label="Name" value={customerName} />
                <Row label="Phone" value={phone} />
                <Row label="Email" value={email} />
                {service === "B2B" && <Row label="Weight" value={weight} />}
                <Row label="Base price" value={naira(pricing.base)} />
                {service === "B2C" && <Row label="Service fee" value={naira(pricing.fee)} />}
                {pricing.distanceAdd > 0 && <Row label="Distance modifier" value={`+${naira(pricing.distanceAdd)}`} />}
                {pricing.expressAdd > 0 && <Row label="Express surcharge" value={`+${naira(pricing.expressAdd)}`} />}
                <Row label="Total" value={naira(pricing.total)} bold />
              </div>
            </div>
          )}

          {/* Step 4: pay */}
          {step === 4 && pricing && (
            <div>
              <h2 className="text-xl font-bold">Pay {naira(pricing.total)}</h2>
              <p className="mt-1 text-sm text-neutral-500">
                You'll be redirected to Paystack's secure checkout to complete payment.
              </p>
              {checkoutError && (
                <div className="mt-4 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-300">
                  {checkoutError}
                </div>
              )}
              {!paid ? (
                <button
                  onClick={async () => {
                    setCheckoutError("");
                    setPaying(true);
                    try {
                      const res = await fetch(`${API_BASE}/api/orders`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                          service,
                          zone: zone.name,
                          weight: service === "B2B" ? weight : undefined,
                          errandType: service === "B2C" ? errandType : undefined,
                          errandItems: service === "B2C" ? errandItems : undefined,
                          express,
                          farBusstop,
                          location,
                          customerName,
                          phone,
                          email,
                        }),
                      });
                      const data = await res.json();
                      if (!res.ok) {
                        setCheckoutError(data.error || "Something went wrong — please try again.");
                        setPaying(false);
                        return;
                      }
                      // Send the customer to Paystack's real checkout page
                      window.location.href = data.authorizationUrl;
                    } catch (err) {
                      setCheckoutError("Couldn't reach the server. Check your connection and try again.");
                      setPaying(false);
                    }
                  }}
                  disabled={paying}
                  className="mt-6 w-full rounded-lg bg-lime-400 py-3 font-bold text-neutral-900 transition-opacity hover:opacity-90 disabled:opacity-60"
                >
                  {paying ? "Redirecting to Paystack…" : `Pay ${naira(pricing.total)} with Paystack`}
                </button>
              ) : (
                <div className="mt-6 rounded-lg border border-lime-400 bg-lime-400/10 p-5">
                  <div className="font-semibold" style={{ color: "#C4F135" }}>✓ Payment confirmed</div>
                  <p className="mt-1 text-sm text-neutral-300">
                    Your rider is being dispatched. Track your order status on the confirmation page (order ID would appear here).
                  </p>
                  <button onClick={reset} className="mt-4 text-sm underline text-neutral-400 hover:text-neutral-200">
                    Start a new order
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Nav */}
          {!paid && (
            <div className="mt-8 flex items-center justify-between border-t border-neutral-800 pt-5">
              <button
                onClick={() => setStep((s) => Math.max(0, s - 1))}
                className={`text-sm text-neutral-500 hover:text-neutral-300 ${step === 0 ? "invisible" : ""}`}
              >
                ← Back
              </button>
              {step < steps.length - 1 && (
                <button
                  onClick={() => canAdvance() && setStep((s) => s + 1)}
                  disabled={!canAdvance()}
                  className="rounded-lg bg-lime-400 px-6 py-2 text-sm font-bold text-neutral-900 disabled:cursor-not-allowed disabled:opacity-30"
                >
                  Continue →
                </button>
              )}
            </div>
          )}
        </div>
      </section>

      <footer className="border-t border-neutral-800 px-5 py-8 text-center text-xs text-neutral-600">
        BikeBlitz — student-powered campus delivery at FUNAAB, Abeokuta. Checkout connects to your website_backend service.
      </footer>
    </div>
  );
}

function Row({ label, value, bold }) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5">
      <span className="text-neutral-500">{label}</span>
      <span className={bold ? "font-bold" : "text-neutral-200"} style={bold ? { color: "#C4F135" } : {}}>
        {value}
      </span>
    </div>
  );
}
