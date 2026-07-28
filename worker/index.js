/**
 * Telegram webhook -> GitHub Actions dispatcher (Cloudflare Worker).
 *
 * Secrets (wrangler secret put): TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_ID, GH_PAT
 * Vars (wrangler.toml):          GH_REPO ("owner/repo")
 * KV binding:                    QA_COUNTER
 */

const DAILY_LIMIT = 30;
const MAX_QUESTION_CHARS = 500;

async function sendTelegram(env, chatId, text) {
  try {
    await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: text }),
    });
  } catch (e) {
    // best effort; never fail the webhook over an ack
  }
}

async function dispatchAnswer(env, question) {
  const resp = await fetch(
    `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/answer.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_PAT}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "qa-worker",
      },
      body: JSON.stringify({ ref: "main", inputs: { question: question } }),
    }
  );
  return resp.status === 204;
}

export default {
  async fetch(request, env) {
    // Telegram only POSTs updates; answer anything else blandly.
    if (request.method !== "POST") return new Response("ok");

    let update;
    try {
      update = await request.json();
    } catch (e) {
      return new Response("ok");
    }

    const msg = update && update.message;
    const text = msg && typeof msg.text === "string" ? msg.text.trim() : "";
    if (!msg || !msg.chat || !text) return new Response("ok");

    // Silent ignore for anyone who is not the owner.
    if (String(msg.chat.id) !== String(env.ALLOWED_CHAT_ID)) return new Response("ok");

    // Ignore bot commands like /start.
    if (text.startsWith("/")) return new Response("ok");

    // Daily quota via KV (UTC date key, expires after 2 days).
    const today = new Date().toISOString().slice(0, 10);
    const key = `count:${today}`;
    const count = parseInt((await env.QA_COUNTER.get(key)) || "0", 10);
    if (count >= DAILY_LIMIT) {
      await sendTelegram(env, msg.chat.id, "今日問答額度用完(30條),聽日再問啦。");
      return new Response("ok");
    }
    await env.QA_COUNTER.put(key, String(count + 1), { expirationTtl: 172800 });

    const question = text.slice(0, MAX_QUESTION_CHARS);
    const ok = await dispatchAnswer(env, question);
    if (ok) {
      await sendTelegram(env, msg.chat.id, "收到,分析緊,大約一分鐘 📊");
    } else {
      await sendTelegram(env, msg.chat.id, "觸發分析失敗,遲啲再試。");
    }
    return new Response("ok");
  },
};
