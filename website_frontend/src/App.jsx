import React, { useState, useMemo, useEffect } from "react";
import React, { useState, useMemo, useEffect } from "react";
import logo from "./assets/IMG_7232.png";

// Live backend URL — update this if you ever redeploy the backend elsewhere.
const API_BASE = "https://bikeblitz-website.onrender.com";

// ---------- Pricing data (mirrors bikeblitz_bot.py exactly) ----------
const ZONES = [
  { id: "z1", name: "Zone 1 - On Campus", desc: "Anywhere within FUNAAB campus", prices: { Light: 300, Medium: 500, Heavy: 700 } },
  { id: "z2", name: "Zone 2 - Near Off Campus", desc: "Harmony, Accord, Zoo, Agbede, Kofesu", prices: { Light: 500, Medium: 700, Heavy: 900 } },
  { id: "z3", name: "Zone 3 - Mid Off Campus", desc: "Labuta, Isolu-Cele, Isolu-FUNIS, Camp", prices: { Light: 700, Medium: 900, Heavy: 1100 } },
  { id: "z4", name: "Zone 4 - Far Off Campus", desc: "Town", prices: { Light: 1200, Medium: 1400, Heavy: 1600 } },
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
  const [photo, setPhoto] = useState(null);
  const [photoPreview, setPhotoPreview] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [deliverError, setDeliverError] = useState("");
  const [justDelivered, setJustDelivered] = useState(false);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState("");
  const [showReportConfirm, setShowReportConfirm] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [reportError, setReportError] = useState("");
  const [justReported, setJustReported] = useState(false);

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

  const handlePhotoChange = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPhoto(file);
    setDeliverError("");
    const reader = new FileReader();
    reader.onload = () => setPhotoPreview(reader.result);
    reader.readAsDataURL(file);
  };

  const submitDelivery = async () => {
    if (!photo) {
      setDeliverError("Please attach a photo showing the delivered item.");
      return;
    }
    setSubmitting(true);
    setDeliverError("");
    try {
      const formData = new FormData();
      formData.append("photo", photo);
      const res = await fetch(`${API_BASE}/api/orders/${reference}/deliver`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) {
        setDeliverError(data.error || "Couldn't confirm delivery — try again.");
        setSubmitting(false);
        return;
      }
      setJustDelivered(true);
      setOrder((prev) => ({ ...prev, status: "Delivered" }));
    } catch (err) {
      setDeliverError("Couldn't reach the server. Check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const canConfirmDelivery = order && order.status !== "Delivered" && order.status !== "Pending Payment" && order.status !== "Cancelled";
  const canCancel = order && order.status !== "Delivered" && order.status !== "Cancelled";
  const canReportNotArrived = order && order.status === "Claimed" && order.riderName;

  const reportNotArrived = async () => {
    setReporting(true);
    setReportError("");
    try {
      const res = await fetch(`${API_BASE}/api/orders/${reference}/report-not-arrived`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setReportError(data.error || "Couldn't report this — try again.");
        setReporting(false);
        return;
      }
      setJustReported(true);
      setShowReportConfirm(false);
      setOrder((prev) => ({ ...prev, status: "Paid", riderName: null }));
    } catch (err) {
      setReportError("Couldn't reach the server. Check your connection and try again.");
    } finally {
      setReporting(false);
    }
  };

  const cancelOrder = async () => {
    setCancelling(true);
    setCancelError("");
    try {
      const res = await fetch(`${API_BASE}/api/orders/${reference}/cancel`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setCancelError(data.error || "Couldn't cancel this order — try again.");
        setCancelling(false);
        return;
      }
      setShowCancelConfirm(false);
      setOrder((prev) => ({ ...prev, status: "Cancelled" }));
    } catch (err) {
      setCancelError("Couldn't reach the server. Check your connection and try again.");
    } finally {
      setCancelling(false);
    }
  };

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

            {order.status === "Claimed" && order.riderLat && order.riderLng && (
              <div className="mt-5 overflow-hidden rounded-lg border border-neutral-800">
                <iframe
                  title="Rider location"
                  className="h-48 w-full"
                  frameBorder="0"
                  src={`https://www.openstreetmap.org/export/embed.html?bbox=${Number(order.riderLng) - 0.006}%2C${Number(order.riderLat) - 0.006}%2C${Number(order.riderLng) + 0.006}%2C${Number(order.riderLat) + 0.006}&layer=mapnik&marker=${order.riderLat}%2C${order.riderLng}`}
                />
                <div className="bg-neutral-800/60 px-3 py-2 text-xs text-neutral-500">
                  {order.riderLocationUpdatedAt ? `Last updated: ${order.riderLocationUpdatedAt}` : "Waiting for rider to share location…"}
                </div>
              </div>
            )}

            {order.pickupCode && order.status !== "Delivered" && (
              <div className="mt-5 rounded-lg border border-lime-400/50 bg-lime-400/10 p-4">
                <div className="text-xs text-neutral-400">Your pickup code</div>
                <div className="mt-1 font-mono text-2xl font-black tracking-widest" style={{ color: "#C4F135" }}>
                  {order.pickupCode}
                </div>
                <div className="mt-1 text-xs text-neutral-400">
                  Only share this with your rider in person, once they arrive to confirm the handoff.
                </div>
              </div>
            )}

            {order.status === "Delivered" && (
              <div className="mt-6 rounded-lg border border-lime-400 bg-lime-400/10 p-4">
                <div className="font-semibold" style={{ color: "#C4F135" }}>
                  ✓ Marked as delivered{justDelivered ? " — thank you!" : ""}
                </div>
              </div>
            )}

            {order.status === "Cancelled" && (
              <div className="mt-6 rounded-lg border border-red-500/50 bg-red-500/10 p-4">
                <div className="font-semibold text-red-300">
                  This order has been cancelled.
                </div>
              </div>
            )}

            {canCancel && !showCancelConfirm && (
              <button
                onClick={() => setShowCancelConfirm(true)}
                className="mt-5 text-xs text-neutral-500 underline hover:text-red-300"
              >
                Cancel this order
              </button>
            )}

            {canCancel && showCancelConfirm && (
              <div className="mt-5 rounded-lg border border-red-500/40 bg-red-500/5 p-4">
                <p className="text-sm text-neutral-300">
                  Are you sure you want to cancel this order? This can't be undone.
                </p>
                {cancelError && (
                  <div className="mt-3 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-300">
                    {cancelError}
                  </div>
                )}
                <div className="mt-3 flex gap-2">
                  <button
                    onClick={cancelOrder}
                    disabled={cancelling}
                    className="flex-1 rounded-lg bg-red-500/90 py-2 text-sm font-bold text-white disabled:opacity-50"
                  >
                    {cancelling ? "Cancelling…" : "Yes, cancel it"}
                  </button>
                  <button
                    onClick={() => setShowCancelConfirm(false)}
                    disabled={cancelling}
                    className="flex-1 rounded-lg border border-neutral-700 py-2 text-sm text-neutral-300"
                  >
                    Never mind
                  </button>
                </div>
              </div>
            )}

            {canReportNotArrived && justReported && (
              <div className="mt-5 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
                Got it — we've reopened your delivery to other riders. You'll be notified once someone new picks it up.
              </div>
            )}

            {canReportNotArrived && !justReported && !showReportConfirm && (
              <button
                onClick={() => setShowReportConfirm(true)}
                className="mt-3 block text-xs text-neutral-500 underline hover:text-amber-300"
              >
                My delivery hasn't arrived yet
              </button>
            )}

            {canReportNotArrived && showReportConfirm && (
              <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4">
                <p className="text-sm text-neutral-300">
                  This will release your order from {order.riderName} and reopen it to other riders. Continue?
                </p>
                {reportError && (
                  <div className="mt-3 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-300">
                    {reportError}
                  </div>
                )}
                <div className="mt-3 flex gap-2">
                  <button
                    onClick={reportNotArrived}
                    disabled={reporting}
                    className="flex-1 rounded-lg bg-amber-500/90 py-2 text-sm font-bold text-neutral-900 disabled:opacity-50"
                  >
                    {reporting ? "Reopening…" : "Yes, reopen it"}
                  </button>
                  <button
                    onClick={() => setShowReportConfirm(false)}
                    disabled={reporting}
                    className="flex-1 rounded-lg border border-neutral-700 py-2 text-sm text-neutral-300"
                  >
                    Never mind
                  </button>
                </div>
              </div>
            )}

            {canConfirmDelivery && (
              <div className="mt-6 border-t border-neutral-800 pt-5">
                <h2 className="text-sm font-bold">Received your order?</h2>
                <p className="mt-1 text-xs text-neutral-500">
                  Attach a photo of the item you received to confirm delivery.
                </p>

                <label className="mt-4 flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-neutral-700 p-5 text-center hover:border-lime-400">
                  {photoPreview ? (
                    <img src={photoPreview} alt="Delivery proof preview" className="max-h-40 rounded-lg object-cover" />
                  ) : (
                    <>
                      <span className="text-2xl">📷</span>
                      <span className="mt-2 text-xs text-neutral-400">Tap to add a photo</span>
                    </>
                  )}
                  <input type="file" accept="image/*" capture="environment" onChange={handlePhotoChange} className="hidden" />
                </label>

                {deliverError && (
                  <div className="mt-3 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-300">
                    {deliverError}
                  </div>
                )}

                <button
                  onClick={submitDelivery}
                  disabled={submitting || !photo}
                  className="mt-4 w-full rounded-lg bg-lime-400 py-3 font-bold text-neutral-900 transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-30"
                >
                  {submitting ? "Confirming…" : "Mark as Delivered"}
                </button>
              </div>
            )}
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
  const [scheduled, setScheduled] = useState(false);
  const [scheduledDateTime, setScheduledDateTime] = useState("");
  const [scheduleError, setScheduleError] = useState("");
  const [farBusstop, setFarBusstop] = useState(false);
  const [location, setLocation] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [paying, setPaying] = useState(false);
  const [paid, setPaid] = useState(false);
  const [checkoutError, setCheckoutError] = useState("");
  const [onlineRiders, setOnlineRiders] = useState(null); // null = not loaded yet

  const [showAccount, setShowAccount] = useState(false);
  const [sessionToken, setSessionToken] = useState(() => (typeof window !== "undefined" ? localStorage.getItem("bb_token") : null));
  const [accountPhone, setAccountPhone] = useState(() => (typeof window !== "undefined" ? localStorage.getItem("bb_phone") : null));
  const [accountEmail, setAccountEmail] = useState(() => (typeof window !== "undefined" ? localStorage.getItem("bb_email") : null));
  const [accountName, setAccountName] = useState(() => (typeof window !== "undefined" ? localStorage.getItem("bb_name") : null));

  const handleLoggedIn = ({ token, phone, email, name }) => {
    localStorage.setItem("bb_token", token);
    localStorage.setItem("bb_phone", phone || "");
    localStorage.setItem("bb_email", email || "");
    localStorage.setItem("bb_name", name || "");
    setSessionToken(token);
    setAccountPhone(phone || "");
    setAccountEmail(email || "");
    setAccountName(name || "");
    if (name) setCustomerName(name);
    if (phone) setPhone(phone);
    if (email) setEmail(email);
  };

  const handleLogout = () => {
    localStorage.removeItem("bb_token");
    localStorage.removeItem("bb_phone");
    localStorage.removeItem("bb_email");
    localStorage.removeItem("bb_name");
    setSessionToken(null);
    setAccountPhone(null);
    setAccountEmail(null);
    setAccountName(null);
  };

  const applyReorder = (order) => {
    setService(order.service);
    const matchedZone = ZONES.find((z) => z.name === order.zone);
    if (matchedZone) setZoneId(matchedZone.id);
    if (order.service === "B2C") {
      const matchedErrand = Object.keys(ERRAND_FEES).find((t) => t === order.errandType) || Object.keys(ERRAND_FEES)[0];
      setErrandType(matchedErrand);
      setErrandItems(order.errandItems || "");
    }
    setExpress((order.deliveryType || "").startsWith("Express"));
    setLocation(order.location || "");
    setCustomerName(accountName || "");
    setPhone(accountPhone || "");
    setShowAccount(false);
    setStep(matchedZone ? 1 : 0);
  };

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/riders/status`)
      .then((res) => res.json())
      .then((data) => {
        if (!cancelled) setOnlineRiders(data.onlineCount ?? 0);
      })
      .catch(() => {
        if (!cancelled) setOnlineRiders(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const zone = ZONES.find((z) => z.id === zoneId);

  const validateSchedule = (value) => {
    if (!value) return "Please pick a date and time.";
    const picked = new Date(value);
    const now = new Date();
    const minAllowed = new Date(now.getTime() + 60 * 60 * 1000);
    if (picked < minAllowed) return "Scheduled deliveries need at least 1 hour's notice.";
    if (picked.getHours() < 9 || picked.getHours() >= 21) return "We only operate 9am–9pm. Please pick a time in that window.";
    const isSameDay = picked.toDateString() === now.toDateString();
    if (isSameDay && picked.getHours() >= 20) return "Same-day scheduling closes at 8pm. Pick an earlier time today, or a time tomorrow.";
    return "";
  };

  const formatScheduled = (value) => {
    if (!value) return "";
    const d = new Date(value);
    return d.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short", year: "numeric" }) +
      " — " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  };

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
    if (step === 0) return !!service && (!scheduled || (scheduledDateTime && !validateSchedule(scheduledDateTime)));
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
    setScheduled(false);
    setScheduledDateTime("");
    setScheduleError("");
    setFarBusstop(false);
    setLocation("");
    setCustomerName("");
    setPhone("");
    setEmail("");
    setPaying(false);
    setPaid(false);
    setCheckoutError("");
  };

  const orderSteps = ["Service", "Zone & type", "Details", "Review", "Pay"];
  const steps = ["Sign in", ...orderSteps];
  const overallIndex = sessionToken ? step + 1 : 0;

  return (
    <div className="min-h-screen w-full bg-neutral-900 text-neutral-100" style={{ fontFamily: "'Helvetica Neue', Arial, sans-serif" }}>
      {/* Header */}
      <header className="border-b border-neutral-800 bg-neutral-900/95 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-4">
          <div className="flex items-center gap-2">
            <img src={logo} alt="BikeBlitz" className="h-9 w-9 rounded-lg" />
            <span className="text-lg font-black tracking-tight">BikeBlitz</span>
          </div>
          <div className="hidden items-center gap-6 text-sm text-neutral-400 sm:flex">
            <span>Pricing</span>
            <span>Zones</span>
            <span>Ride for us</span>
          </div>
          <button
            onClick={() => setShowAccount(true)}
            className="rounded-full border border-neutral-700 px-3 py-1 font-mono text-xs text-neutral-300 hover:border-lime-400"
          >
            {accountName ? `👤 ${accountName.split(" ")[0]}` : "Sign in"}
          </button>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden border-b border-neutral-800 px-5 py-14">
        <div
          className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full opacity-20 blur-3xl"
          style={{ background: "#8A3820" }}
        />
        <div className="mx-auto max-w-5xl">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div className="inline-block rounded-full border px-3 py-1 font-mono text-xs" style={{ borderColor: "#8A3820", color: "#c9724f" }}>
              Same-day · 9am–9pm · cutoff 8pm
            </div>
            {onlineRiders !== null && (
              <div
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono text-xs ${
                  onlineRiders > 0 ? "border-lime-400/50 text-lime-300" : "border-neutral-600 text-neutral-400"
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${onlineRiders > 0 ? "bg-lime-400" : "bg-neutral-500"}`} />
                {onlineRiders > 0 ? `${onlineRiders} rider${onlineRiders !== 1 ? "s" : ""} online now` : "No riders online right now"}
              </div>
            )}
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
            <RouteDot key={label} index={i + 1} label={label} active={overallIndex === i} done={overallIndex > i} />
          ))}
        </div>

        {/* Card */}
        <div className="rounded-2xl border border-neutral-800 bg-neutral-850 bg-neutral-800/40 p-6 sm:p-8">
          <div className="mb-6 flex items-center justify-between md:hidden">
            <span className="font-mono text-xs text-neutral-500">
              Step {overallIndex + 1} of {steps.length}
            </span>
            <span className="text-sm font-semibold">{steps[overallIndex]}</span>
          </div>

          {!sessionToken && (
            <InlineAuth
              onLoggedIn={(data) => {
                handleLoggedIn(data);
              }}
            />
          )}

          {sessionToken && (
          <>
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
                <input
                  type="checkbox"
                  checked={express}
                  onChange={(e) => {
                    setExpress(e.target.checked);
                    if (e.target.checked) {
                      setScheduled(false);
                      setScheduledDateTime("");
                      setScheduleError("");
                    }
                  }}
                  className="accent-lime-400"
                />
                Express delivery (+{naira(EXPRESS_SURCHARGE)}, priority handling)
              </label>

              <label className="mt-3 flex items-center gap-2 text-sm text-neutral-400">
                <input
                  type="checkbox"
                  checked={scheduled}
                  onChange={(e) => {
                    setScheduled(e.target.checked);
                    if (e.target.checked) setExpress(false);
                    else {
                      setScheduledDateTime("");
                      setScheduleError("");
                    }
                  }}
                  className="accent-lime-400"
                />
                Schedule for later (pick a date & time)
              </label>

              {scheduled && (
                <div className="mt-3 rounded-lg border border-neutral-700 bg-neutral-900 p-4">
                  <label className="mb-1 block text-xs font-semibold text-neutral-400">Delivery date & time</label>
                  <input
                    type="datetime-local"
                    value={scheduledDateTime}
                    onChange={(e) => {
                      setScheduledDateTime(e.target.value);
                      setScheduleError(validateSchedule(e.target.value));
                    }}
                    className="w-full rounded-lg border border-neutral-700 bg-neutral-800 p-3 text-sm text-neutral-100 outline-none focus:border-lime-400"
                  />
                  <p className="mt-2 text-xs text-neutral-500">
                    Available daily 9am–9pm. Needs at least 1 hour's notice. Same-day scheduling closes at 8pm.
                  </p>
                  {scheduleError && (
                    <div className="mt-2 rounded-lg border border-red-500/50 bg-red-500/10 p-2 text-xs text-red-300">
                      {scheduleError}
                    </div>
                  )}
                  {scheduledDateTime && !scheduleError && (
                    <div className="mt-2 text-xs" style={{ color: "#C4F135" }}>
                      ✓ Scheduled for {formatScheduled(scheduledDateTime)}
                    </div>
                  )}
                </div>
              )}
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
                {scheduled && scheduledDateTime && <Row label="Scheduled for" value={formatScheduled(scheduledDateTime)} />}
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
              {onlineRiders === 0 && (
                <div className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
                  ⚠️ No riders are online right now. Your order will still go through and be broadcast
                  the moment payment confirms, but it may take longer than usual to be claimed.
                </div>
              )}
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
                          scheduledTime: scheduled && scheduledDateTime ? formatScheduled(scheduledDateTime) : undefined,
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
              {step < orderSteps.length - 1 && (
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
          </>
          )}
        </div>
      </section>

      <footer className="border-t border-neutral-800 px-5 py-8 text-center text-xs text-neutral-600">
        BikeBlitz — student-powered campus delivery at FUNAAB, Abeokuta. Checkout connects to your website_backend service.
      </footer>

      {showAccount && (
        <AccountPanel
          sessionToken={sessionToken}
          accountPhone={accountPhone}
          accountEmail={accountEmail}
          accountName={accountName}
          onLoggedIn={handleLoggedIn}
          onLogout={handleLogout}
          onReorder={applyReorder}
          onClose={() => setShowAccount(false)}
        />
      )}
    </div>
  );
}

function InlineAuth({ onLoggedIn }) {
  const [phase, setPhase] = useState("email"); // email | code
  const [emailInput, setEmailInput] = useState("");
  const [phoneInput, setPhoneInput] = useState("");
  const [nameInput, setNameInput] = useState("");
  const [codeInput, setCodeInput] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const sendCode = async () => {
    if (!emailInput.trim() || !/\S+@\S+\.\S+/.test(emailInput.trim())) {
      setError("Enter a valid email address.");
      return;
    }
    if (!phoneInput.trim()) { setError("Enter your phone number."); return; }
    setBusy(true); setError("");
    try {
      const res = await fetch(`${API_BASE}/api/auth/send-otp`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: emailInput.trim() }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error || "Couldn't send code."); setBusy(false); return; }
      setPhase("code");
    } catch (e) {
      setError("Couldn't reach the server.");
    }
    setBusy(false);
  };

  const verifyCode = async () => {
    if (!codeInput.trim()) { setError("Enter the code you received."); return; }
    setBusy(true); setError("");
    try {
      const res = await fetch(`${API_BASE}/api/auth/verify-otp`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: emailInput.trim(),
          code: codeInput.trim(),
          name: nameInput.trim(),
          phone: phoneInput.trim(),
        }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error || "That code didn't work."); setBusy(false); return; }
      onLoggedIn({ token: data.token, email: data.email, phone: data.phone, name: data.name || nameInput.trim() });
    } catch (e) {
      setError("Couldn't reach the server.");
    }
    setBusy(false);
  };

  return (
    <div>
      <h2 className="text-xl font-bold">
        {phase === "email" ? "Let's verify it's you" : "Enter your code"}
      </h2>
      <p className="mt-1 text-sm text-neutral-500">
        {phase === "email"
          ? "We need this to keep your orders and delivery details secure."
          : `Check ${emailInput} for a 4-digit code (and check spam, just in case).`}
      </p>

      {phase === "email" && (
        <div className="mt-5">
          <label className="mb-1 block text-sm font-semibold">Email address</label>
          <input
            value={emailInput}
            onChange={(e) => setEmailInput(e.target.value)}
            placeholder="you@example.com"
            type="email"
            className="w-full rounded-lg border border-neutral-700 bg-neutral-900 p-3 text-sm outline-none focus:border-lime-400"
          />
          <label className="mb-1 mt-3 block text-sm font-semibold">Phone number</label>
          <input
            value={phoneInput}
            onChange={(e) => setPhoneInput(e.target.value)}
            placeholder="0801 234 5678"
            className="w-full rounded-lg border border-neutral-700 bg-neutral-900 p-3 text-sm outline-none focus:border-lime-400"
          />
          <label className="mb-1 mt-3 block text-sm font-semibold">Your name</label>
          <input
            value={nameInput}
            onChange={(e) => setNameInput(e.target.value)}
            placeholder="Full name"
            className="w-full rounded-lg border border-neutral-700 bg-neutral-900 p-3 text-sm outline-none focus:border-lime-400"
          />
          {error && <p className="mt-2 text-sm text-red-300">{error}</p>}
          <button
            onClick={sendCode}
            disabled={busy}
            className="mt-4 w-full rounded-lg bg-lime-400 py-3 font-bold text-neutral-900 disabled:opacity-50"
          >
            {busy ? "Sending…" : "Send verification code"}
          </button>
        </div>
      )}

      {phase === "code" && (
        <div className="mt-5">
          <input
            value={codeInput}
            onChange={(e) => setCodeInput(e.target.value)}
            placeholder="1234"
            inputMode="numeric"
            className="w-full rounded-lg border border-neutral-700 bg-neutral-900 p-3 text-center font-mono text-lg tracking-widest outline-none focus:border-lime-400"
          />
          {error && <p className="mt-2 text-sm text-red-300">{error}</p>}
          <button
            onClick={verifyCode}
            disabled={busy}
            className="mt-4 w-full rounded-lg bg-lime-400 py-3 font-bold text-neutral-900 disabled:opacity-50"
          >
            {busy ? "Verifying…" : "Verify & continue"}
          </button>
          <button onClick={() => setPhase("email")} className="mt-2 w-full text-sm text-neutral-500 hover:text-neutral-300">
            ← Change email
          </button>
        </div>
      )}
    </div>
  );
}

function AccountPanel({ sessionToken, accountPhone, accountEmail, accountName, onLoggedIn, onLogout, onReorder, onClose }) {
  const [phase, setPhase] = useState(sessionToken ? "history" : "email"); // email | code | history
  const [emailInput, setEmailInput] = useState("");
  const [phoneInput, setPhoneInput] = useState("");
  const [nameInput, setNameInput] = useState("");
  const [codeInput, setCodeInput] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [orders, setOrders] = useState(null);

  useEffect(() => {
    if (phase !== "history" || !sessionToken) return;
    let cancelled = false;
    fetch(`${API_BASE}/api/orders/history`, { headers: { "X-Session-Token": sessionToken } })
      .then((res) => res.json())
      .then((data) => { if (!cancelled) setOrders(data.orders || []); })
      .catch(() => { if (!cancelled) setOrders([]); });
    return () => { cancelled = true; };
  }, [phase, sessionToken]);

  const sendCode = async () => {
    if (!emailInput.trim() || !/\S+@\S+\.\S+/.test(emailInput.trim())) {
      setError("Enter a valid email address.");
      return;
    }
    setBusy(true); setError("");
    try {
      const res = await fetch(`${API_BASE}/api/auth/send-otp`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: emailInput.trim() }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error || "Couldn't send code."); setBusy(false); return; }
      setPhase("code");
    } catch (e) {
      setError("Couldn't reach the server.");
    }
    setBusy(false);
  };

  const verifyCode = async () => {
    if (!codeInput.trim()) { setError("Enter the code you received."); return; }
    setBusy(true); setError("");
    try {
      const res = await fetch(`${API_BASE}/api/auth/verify-otp`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: emailInput.trim(),
          code: codeInput.trim(),
          name: nameInput.trim(),
          phone: phoneInput.trim(),
        }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error || "That code didn't work."); setBusy(false); return; }
      onLoggedIn({ token: data.token, email: data.email, phone: data.phone, name: data.name || nameInput.trim() });
      setPhase("history");
    } catch (e) {
      setError("Couldn't reach the server.");
    }
    setBusy(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-t-2xl border border-neutral-800 bg-neutral-900 p-6 sm:rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold">{phase === "history" ? "Your account" : "Sign in"}</h2>
          <button onClick={onClose} className="text-neutral-500 hover:text-neutral-200">✕</button>
        </div>

        {phase === "email" && (
          <div>
            <label className="mb-1 block text-sm font-semibold">Email address</label>
            <input
              value={emailInput}
              onChange={(e) => setEmailInput(e.target.value)}
              placeholder="you@example.com"
              type="email"
              className="w-full rounded-lg border border-neutral-700 bg-neutral-800 p-3 text-sm outline-none focus:border-lime-400"
            />
            <label className="mb-1 mt-3 block text-sm font-semibold">Phone number</label>
            <input
              value={phoneInput}
              onChange={(e) => setPhoneInput(e.target.value)}
              placeholder="0801 234 5678"
              className="w-full rounded-lg border border-neutral-700 bg-neutral-800 p-3 text-sm outline-none focus:border-lime-400"
            />
            <label className="mb-1 mt-3 block text-sm font-semibold">Your name (optional)</label>
            <input
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              placeholder="Full name"
              className="w-full rounded-lg border border-neutral-700 bg-neutral-800 p-3 text-sm outline-none focus:border-lime-400"
            />
            {error && <p className="mt-2 text-sm text-red-300">{error}</p>}
            <button
              onClick={sendCode}
              disabled={busy}
              className="mt-4 w-full rounded-lg bg-lime-400 py-3 font-bold text-neutral-900 disabled:opacity-50"
            >
              {busy ? "Sending…" : "Send verification code"}
            </button>
          </div>
        )}

        {phase === "code" && (
          <div>
            <p className="mb-3 text-sm text-neutral-400">Enter the code sent to {emailInput}</p>
            <input
              value={codeInput}
              onChange={(e) => setCodeInput(e.target.value)}
              placeholder="1234"
              inputMode="numeric"
              className="w-full rounded-lg border border-neutral-700 bg-neutral-800 p-3 text-center font-mono text-lg tracking-widest outline-none focus:border-lime-400"
            />
            {error && <p className="mt-2 text-sm text-red-300">{error}</p>}
            <button
              onClick={verifyCode}
              disabled={busy}
              className="mt-4 w-full rounded-lg bg-lime-400 py-3 font-bold text-neutral-900 disabled:opacity-50"
            >
              {busy ? "Verifying…" : "Verify & sign in"}
            </button>
            <button onClick={() => setPhase("email")} className="mt-2 w-full text-sm text-neutral-500 hover:text-neutral-300">
              ← Change email
            </button>
          </div>
        )}

        {phase === "history" && (
          <div>
            <p className="mb-3 text-sm text-neutral-400">Signed in as {accountName || accountEmail || accountPhone}</p>
            {orders === null && <p className="text-sm text-neutral-500">Loading your orders…</p>}
            {orders && orders.length === 0 && <p className="text-sm text-neutral-500">No past orders yet.</p>}
            {orders && orders.length > 0 && (
              <div className="max-h-80 space-y-2 overflow-y-auto">
                {orders.map((o) => (
                  <div key={o.reference} className="rounded-lg border border-neutral-800 p-3 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold">{o.zone}</span>
                      <span className="font-mono text-xs text-neutral-500">{o.status}</span>
                    </div>
                    <div className="mt-1 text-xs text-neutral-500">{o.timestamp} — ₦{Number(o.total || 0).toLocaleString()}</div>
                    <button
                      onClick={() => onReorder(o)}
                      className="mt-2 text-xs font-semibold underline"
                      style={{ color: "#C4F135" }}
                    >
                      Reorder this
                    </button>
                  </div>
                ))}
              </div>
            )}
            <button onClick={onLogout} className="mt-4 w-full text-sm text-neutral-500 hover:text-neutral-300">
              Sign out
            </button>
          </div>
        )}
      </div>
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
