"use client";

import { FormEvent, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft,
  ArrowUpRight,
  BarChart3,
  Building2,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileText,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from "lucide-react";

const API_URL = "http://localhost:8000";

const suggestions = [
  {
    icon: Building2,
    label: "Company",
    question: "What was Apple's revenue in 2024?",
  },
  {
    icon: BarChart3,
    label: "Compare",
    question: "Compare NVIDIA and AMD gross margins",
  },
  {
    icon: FileText,
    label: "Filings",
    question: "What risks did Tesla mention in its latest 10-K?",
  },
  {
    icon: BarChart3,
    label: "Trend",
    question: "Show Tesla's revenue growth over the last 5 years",
  },
];

const navigation = [
  { icon: Sparkles, label: "Ask", active: true },
  { icon: Building2, label: "Companies" },
  { icon: FileText, label: "Filings" },
  { icon: BarChart3, label: "Metrics" },
];

type Citation = {
  label?: string;
  title?: string;
  source?: string;
  excerpt?: string;
  [key: string]: unknown;
};

type AskResponse = {
  request_id?: string;
  question?: string;
  answer?: string;
  route?: string;
  citations?: Citation[];
  sql?: string;
  verification?: unknown;
  warnings?: string[];
  reasoning?: string;
  usage?: Record<string, unknown>;
  elapsed_ms?: number;
  [key: string]: unknown;
};

type StageName =
  | "router"
  | "warehouse"
  | "retrieval"
  | "verification"
  | "synthesis";

type StageState = "pending" | "active" | "complete";

type Stage = {
  key: StageName;
  label: string;
  description: string;
  state: StageState;
};

const initialStages: Stage[] = [
  {
    key: "router",
    label: "ROUTER",
    description: "Classifying your financial question",
    state: "pending",
  },
  {
    key: "warehouse",
    label: "WAREHOUSE",
    description: "Querying structured financial data",
    state: "pending",
  },
  {
    key: "retrieval",
    label: "RETRIEVAL",
    description: "Searching SEC filing evidence",
    state: "pending",
  },
  {
    key: "verification",
    label: "VERIFICATION",
    description: "Cross-checking evidence",
    state: "pending",
  },
  {
    key: "synthesis",
    label: "SYNTHESIS",
    description: "Preparing the answer",
    state: "pending",
  },
];

export default function Home() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [stages, setStages] = useState<Stage[]>(initialStages);

  async function askFinLens(value?: string) {
    const query = (value ?? question).trim();

    if (!query || loading) return;

    setQuestion(query);
    setAnswer(null);
    setError("");
    setLoading(true);
    setStages(initialStages);

    try {
      const response = await fetch(`${API_URL}/ask/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({
          question: query,
        }),
      });

      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }

      if (!response.body) {
        throw new Error("The streaming response did not contain a body.");
      }

      let streamedAnswer = "";

      await consumeStream(response.body, {
        onEvent: (eventName, payload) => {
          if (eventName === "token") {
            const text =
              typeof payload === "string"
                ? payload
                : payload?.text || "";

            streamedAnswer += text;

            setStages((current) =>
              current.map((stage) =>
                stage.key === "synthesis"
                  ? { ...stage, state: "active" }
                  : stage
              )
            );

            return;
          }

          handleStreamEvent(eventName, payload);
        },

        onComplete: (metadata) => {
          setStages((current) =>
            current.map((stage) => ({
              ...stage,
              state: "complete",
            }))
          );

          setAnswer({
            ...metadata,
            question: query,
            answer: streamedAnswer.trim(),
          });

          setLoading(false);
        },
      });
    } catch (err) {
      console.error(err);

      setError(
        err instanceof Error
          ? err.message
          : "FinLens could not complete the analysis."
      );

      setLoading(false);
    }
  }

  function handleStreamEvent(eventName: string, payload: any) {
    switch (eventName) {
      case "status":
        if (payload?.stage === "routing") {
          activateStage("router");
        }
        return;

      case "route":
        completeStage("router");
        activateStage("warehouse");
        return;

      case "sql":
        completeStage("warehouse");
        activateStage("retrieval");
        return;

      case "citation":
        completeStage("retrieval");
        activateStage("verification");
        return;

      case "verification":
        completeStage("verification");
        activateStage("synthesis");
        return;

      case "token":
        activateStage("synthesis");
        return;

      default:
        return;
    }
  }

  function activateStage(key: StageName) {
    setStages((current) =>
      current.map((stage) =>
        stage.key === key
          ? { ...stage, state: "active" }
          : stage.state === "active"
            ? { ...stage, state: "complete" }
            : stage
      )
    );
  }

  function completeStage(key: StageName) {
    setStages((current) =>
      current.map((stage) =>
        stage.key === key ? { ...stage, state: "complete" } : stage
      )
    );
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    askFinLens();
  }

  function reset() {
    setAnswer(null);
    setError("");
    setQuestion("");
    setLoading(false);
    setStages(initialStages);
  }

  return (
    <main className="min-h-screen bg-[#07090c] text-[#f3f6f8]">
      <div className="flex min-h-screen">
        <aside className="hidden w-[224px] shrink-0 border-r border-[#1b2027] bg-[#0a0d11] md:flex md:flex-col">
          <div className="flex h-[72px] items-center border-b border-[#1b2027] px-6">
            <div>
              <div className="text-[17px] font-semibold tracking-[0.18em]">
                FINLENS
              </div>
              <div className="mt-0.5 text-[9px] tracking-[0.2em] text-[#66717d]">
                INTELLIGENCE TERMINAL
              </div>
            </div>
          </div>

          <nav className="flex-1 px-3 py-5">
            <div className="mb-3 px-3 text-[10px] font-medium uppercase tracking-[0.18em] text-[#4e5863]">
              Workspace
            </div>

            <div className="space-y-1">
              {navigation.map((item) => {
                const Icon = item.icon;

                return (
                  <button
                    key={item.label}
                    className={`flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-[13px] transition ${
                      item.active
                        ? "bg-[#111820] text-[#59d6ff]"
                        : "text-[#89939e] hover:bg-[#0f141a] hover:text-[#dce2e7]"
                    }`}
                  >
                    <Icon size={16} strokeWidth={1.7} />
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </div>

            <div className="mb-3 mt-9 px-3 text-[10px] font-medium uppercase tracking-[0.18em] text-[#4e5863]">
              System
            </div>

            <button className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-[13px] text-[#89939e] transition hover:bg-[#0f141a] hover:text-[#dce2e7]">
              <Clock3 size={16} strokeWidth={1.7} />
              <span>History</span>
            </button>

            <button className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-[13px] text-[#89939e] transition hover:bg-[#0f141a] hover:text-[#dce2e7]">
              <Settings size={16} strokeWidth={1.7} />
              <span>Settings</span>
            </button>
          </nav>

          <div className="border-t border-[#1b2027] p-4">
            <div className="flex items-center gap-2.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#151b21] text-[10px] font-medium text-[#aeb7c0]">
                IS
              </div>
              <div>
                <div className="text-[11px] text-[#c5ccd3]">Research</div>
                <div className="text-[10px] text-[#59636e]">
                  Analyst workspace
                </div>
              </div>
            </div>
          </div>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-[72px] items-center justify-between border-b border-[#1b2027] px-5 md:px-8">
            <div className="flex items-center gap-3 md:hidden">
              <div className="text-[16px] font-semibold tracking-[0.16em]">
                FINLENS
              </div>
            </div>

            <div className="hidden items-center gap-2 text-[11px] text-[#69747f] md:flex">
              <span className="font-mono">WORKSPACE</span>
              <ChevronRight size={13} />
              <span className="text-[#a8b0b8]">ASK</span>
            </div>

            <div className="ml-auto flex items-center gap-5">
              <div className="hidden items-center gap-2 text-[10px] uppercase tracking-[0.14em] text-[#67727d] sm:flex">
                <span className="h-1.5 w-1.5 rounded-full bg-[#43d58c]" />
                Systems operational
              </div>

              <div className="flex h-7 w-7 items-center justify-center rounded-full border border-[#252c34] bg-[#11151a] text-[10px] text-[#aeb7c0]">
                IS
              </div>
            </div>
          </header>

          <div className="flex flex-1 justify-center overflow-auto">
            <AnimatePresence mode="wait">
              {!answer && !loading && !error ? (
                <HomeView
                  question={question}
                  setQuestion={setQuestion}
                  onSubmit={handleSubmit}
                  askFinLens={askFinLens}
                  loading={loading}
                />
              ) : loading ? (
                <AnalysisState
                  key="analysis"
                  question={question}
                  stages={stages}
                />
              ) : error ? (
                <ErrorState key="error" error={error} onBack={reset} />
              ) : (
                <AnswerView
                  key="answer"
                  question={question}
                  data={answer!}
                  onBack={reset}
                />
              )}
            </AnimatePresence>
          </div>
        </section>
      </div>
    </main>
  );
}

function HomeView({
  question,
  setQuestion,
  onSubmit,
  askFinLens,
  loading,
}: {
  question: string;
  setQuestion: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  askFinLens: (value?: string) => void;
  loading: boolean;
}) {
  return (
    <motion.div
      key="home"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, y: -8 }}
      className="w-full max-w-[980px] px-5 pb-20 pt-16 md:px-10 md:pt-24"
    >
      <div>
        <div className="mb-3 flex items-center justify-center gap-2 text-[10px] font-medium uppercase tracking-[0.24em] text-[#65717d]">
          <span className="h-px w-8 bg-[#28313a]" />
          SEC intelligence terminal
          <span className="h-px w-8 bg-[#28313a]" />
        </div>

        <h1 className="text-center text-[34px] font-medium tracking-[-0.035em] text-[#f2f5f7] md:text-[46px]">
          Ask FinLens.
        </h1>

        <p className="mx-auto mt-3 max-w-[560px] text-center text-[14px] leading-6 text-[#737e89]">
          Query financial data, filings, and company intelligence in natural
          language.
        </p>
      </div>

      <QueryBox
        question={question}
        setQuestion={setQuestion}
        onSubmit={onSubmit}
        loading={loading}
      />

      <div className="mx-auto mt-8 max-w-[760px]">
        <div className="mb-3 px-1 text-[10px] uppercase tracking-[0.18em] text-[#505b66]">
          Try asking
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          {suggestions.map((item, index) => {
            const Icon = item.icon;

            return (
              <motion.button
                key={item.question}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  delay: 0.05 + index * 0.05,
                  duration: 0.3,
                }}
                onClick={() => askFinLens(item.question)}
                className="group flex min-h-[72px] items-center gap-3 rounded-lg border border-[#1d242c] bg-[#0b0f14] px-4 text-left transition hover:border-[#34414c] hover:bg-[#0e1319]"
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[#222b33] bg-[#11161c] text-[#65717c] transition group-hover:text-[#59d6ff]">
                  <Icon size={15} strokeWidth={1.6} />
                </div>

                <div className="min-w-0">
                  <div className="mb-1 text-[9px] uppercase tracking-[0.16em] text-[#4f5a65]">
                    {item.label}
                  </div>
                  <div className="truncate text-[12px] text-[#aab3bb] group-hover:text-[#d8dee3]">
                    {item.question}
                  </div>
                </div>

                <ChevronRight
                  size={14}
                  className="ml-auto shrink-0 text-[#3f4851]"
                />
              </motion.button>
            );
          })}
        </div>
      </div>

      <div className="mx-auto mt-12 flex max-w-[760px] flex-wrap items-center justify-center gap-x-6 gap-y-2 border-t border-[#151b21] pt-5 text-[10px] text-[#4e5963]">
        <span className="flex items-center gap-1.5">
          <ShieldCheck size={13} />
          SEC filings
        </span>
        <span className="hidden h-3 w-px bg-[#252c33] sm:block" />
        <span>Structured financial data</span>
        <span className="hidden h-3 w-px bg-[#252c33] sm:block" />
        <span>Evidence-backed answers</span>
      </div>
    </motion.div>
  );
}

function QueryBox({
  question,
  setQuestion,
  onSubmit,
  loading,
}: {
  question: string;
  setQuestion: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  loading: boolean;
}) {
  return (
    <motion.form
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      onSubmit={onSubmit}
      className="mx-auto mt-10 max-w-[760px]"
    >
      <div className="group rounded-xl border border-[#29323b] bg-[#0c1015] p-2 shadow-[0_20px_70px_rgba(0,0,0,0.28)] transition-colors focus-within:border-[#3b7182]">
        <div className="flex min-h-[122px] flex-col">
          <div className="flex flex-1 items-start gap-3 px-4 pt-3">
            <Search
              size={18}
              strokeWidth={1.7}
              className="mt-1 text-[#596672]"
            />

            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder="Ask a financial question..."
              disabled={loading}
              className="min-h-[70px] flex-1 resize-none bg-transparent text-[15px] leading-6 text-[#e9edf0] outline-none placeholder:text-[#4e5964]"
            />
          </div>

          <div className="flex items-center justify-between px-3 pb-2">
            <div className="hidden items-center gap-2 text-[10px] text-[#4e5964] sm:flex">
              <span className="rounded border border-[#252d35] px-1.5 py-0.5 font-mono">
                ENTER
              </span>
              <span>to ask</span>
            </div>

            <button
              type="submit"
              disabled={!question.trim() || loading}
              className="ml-auto flex items-center gap-2 rounded-md bg-[#dcebf0] px-3.5 py-2 text-[11px] font-medium text-[#071015] transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              Ask FinLens
              <ArrowUpRight size={14} />
            </button>
          </div>
        </div>
      </div>
    </motion.form>
  );
}

function AnalysisState({
  question,
  stages,
}: {
  question: string;
  stages: Stage[];
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="w-full max-w-[760px] px-5 pb-20 pt-16 md:pt-24"
    >
      <div className="mb-10">
        <div className="mb-3 text-[10px] uppercase tracking-[0.2em] text-[#596570]">
          FINLENS ANALYSIS
        </div>

        <div className="text-[18px] leading-7 text-[#dce2e7]">
          {question}
        </div>
      </div>

      <div className="rounded-xl border border-[#202831] bg-[#0b0f14] p-5">
        {stages.map((stage, index) => (
          <StageRow
            key={stage.key}
            stage={stage}
            last={index === stages.length - 1}
          />
        ))}
      </div>
    </motion.div>
  );
}

function StageRow({
  stage,
  last,
}: {
  stage: Stage;
  last: boolean;
}) {
  const active = stage.state === "active";
  const complete = stage.state === "complete";

  return (
    <motion.div
      layout
      className={`flex items-center gap-4 ${
        !last ? "border-b border-[#161d24] pb-4" : ""
      } ${stage.state !== "pending" || !last ? "pt-4" : ""}`}
    >
      <div
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border ${
          active
            ? "border-[#3d8da5] bg-[#10242b] text-[#59d6ff]"
            : complete
              ? "border-[#285e49] bg-[#0d1d17] text-[#43d58c]"
              : "border-[#29323a] text-[#4b5661]"
        }`}
      >
        {complete ? (
          <CheckCircle2 size={14} />
        ) : active ? (
          <span className="h-2 w-2 animate-pulse rounded-full bg-[#59d6ff]" />
        ) : (
          <span className="h-1.5 w-1.5 rounded-full bg-[#39434d]" />
        )}
      </div>

      <div>
        <div
          className={`font-mono text-[10px] tracking-[0.12em] ${
            active
              ? "text-[#59d6ff]"
              : complete
                ? "text-[#43d58c]"
                : "text-[#66717b]"
          }`}
        >
          {stage.label}
        </div>

        <div className="mt-1 text-[11px] text-[#65707b]">
          {stage.description}
        </div>
      </div>
    </motion.div>
  );
}

async function consumeStream(
  body: ReadableStream<Uint8Array>,
  handlers: {
    onEvent: (eventName: string, payload: any) => void;
    onComplete: (answer: AskResponse) => void;
  }
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();

  let buffer = "";
  let currentEvent = "message";
  let currentData: string[] = [];

  while (true) {
    const { value, done } = await reader.read();

    if (done) {
      buffer += decoder.decode();
      break;
    }

    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const rawLine of lines) {
      const line = rawLine.replace(/\r$/, "");

      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        currentData.push(line.slice(5).trim());
      } else if (line === "") {
        if (currentData.length > 0) {
          const rawPayload = currentData.join("\n");

          let payload: any = rawPayload;

          try {
            payload = JSON.parse(rawPayload);
          } catch {
            // Keep plain-text payload.
          }

          if (
            currentEvent === "done" ||
            currentEvent === "complete" ||
            currentEvent === "finished"
          ) {
            handlers.onComplete(normalizeAnswer(payload));
          } else {
            handlers.onEvent(currentEvent, payload);
          }
        }

        currentEvent = "message";
        currentData = [];
      }
    }
  }

  if (currentData.length > 0) {
    const rawPayload = currentData.join("\n");

    let payload: any = rawPayload;

    try {
      payload = JSON.parse(rawPayload);
    } catch {
      // Keep plain-text payload.
    }

    if (
      currentEvent === "done" ||
      currentEvent === "complete" ||
      currentEvent === "finished"
    ) {
      handlers.onComplete(normalizeAnswer(payload));
    } else {
      handlers.onEvent(currentEvent, payload);
    }
  }
}

function normalizeAnswer(payload: any): AskResponse {
  if (payload?.answer) {
    return payload;
  }

  if (payload?.result?.answer) {
    return payload.result;
  }

  if (payload?.response?.answer) {
    return payload.response;
  }

  return {
    answer:
      typeof payload === "string"
        ? payload
        : payload?.message || "No answer was returned.",
    ...payload,
  };
}

function ErrorState({
  error,
  onBack,
}: {
  error: string;
  onBack: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex w-full max-w-[700px] flex-col items-center px-5 pt-24 text-center"
    >
      <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-full border border-[#5b342f] bg-[#1b100f] text-[#e37d69]">
        <TriangleAlert size={19} />
      </div>

      <div className="text-[20px] font-medium text-[#e9edef]">
        FinLens couldn't complete that query
      </div>

      <p className="mt-3 max-w-[500px] text-[12px] leading-6 text-[#737e89]">
        {error}
      </p>

      <button
        onClick={onBack}
        className="mt-7 flex items-center gap-2 rounded-md border border-[#303943] bg-[#11161c] px-4 py-2.5 text-[11px] text-[#cbd2d8] transition hover:border-[#46515c] hover:bg-[#151b21]"
      >
        <ArrowLeft size={14} />
        Try again
      </button>
    </motion.div>
  );
}

function AnswerView({
  question,
  data,
  onBack,
}: {
  question: string;
  data: AskResponse;
  onBack: () => void;
}) {
  const citations = Array.isArray(data.citations) ? data.citations : [];
  const warnings = Array.isArray(data.warnings) ? data.warnings : [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="w-full max-w-[920px] px-5 pb-20 pt-10 md:px-10 md:pt-14"
    >
      <button
        onClick={onBack}
        className="mb-8 flex items-center gap-2 text-[11px] text-[#697580] transition hover:text-[#d9e0e5]"
      >
        <ArrowLeft size={14} />
        New question
      </button>

      <div className="mb-8">
        <div className="mb-3 text-[10px] uppercase tracking-[0.2em] text-[#596570]">
          QUESTION
        </div>

        <div className="text-[17px] leading-7 text-[#dce2e7]">
          {question}
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-[#28323b] bg-[#0b0f14]">
        <div className="border-b border-[#1d252d] px-6 py-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-[#69747e]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#43d58c]" />
              FinLens answer
            </div>

            {data.route && (
              <div className="rounded border border-[#27313a] px-2 py-1 font-mono text-[9px] uppercase tracking-[0.12em] text-[#64717c]">
                {data.route}
              </div>
            )}
          </div>
        </div>

        <div className="px-6 py-7">
          <div className="whitespace-pre-wrap text-[16px] leading-8 text-[#e7ebee]">
            {data.answer || "No answer was returned."}
          </div>

          <div className="mt-7 flex flex-wrap items-center gap-4 border-t border-[#182028] pt-5">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] text-[#43d58c]">
              <CheckCircle2 size={14} />
              {data.verification ? "Verified" : "Evidence returned"}
            </div>

            {data.elapsed_ms !== undefined && (
              <div className="font-mono text-[10px] text-[#56616c]">
                {Math.round(data.elapsed_ms)} ms
              </div>
            )}

            {data.request_id && (
              <div className="font-mono text-[10px] text-[#56616c]">
                {data.request_id}
              </div>
            )}
          </div>
        </div>
      </div>

      {warnings.length > 0 && (
        <div className="mt-4 rounded-lg border border-[#55451f] bg-[#17130b] p-4">
          <div className="flex gap-3">
            <TriangleAlert
              size={15}
              className="mt-0.5 shrink-0 text-[#d8a84c]"
            />

            <div>
              <div className="mb-1 text-[10px] uppercase tracking-[0.16em] text-[#d8a84c]">
                Warning
              </div>

              <div className="space-y-1 text-[11px] leading-5 text-[#a99b7d]">
                {warnings.map((warning, index) => (
                  <div key={index}>{warning}</div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {citations.length > 0 && (
        <div className="mt-5">
          <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-[#596570]">
            Sources
          </div>

          <div className="space-y-2">
            {citations.map((citation, index) => (
              <div
                key={index}
                className="rounded-lg border border-[#1d252d] bg-[#0b0f14] p-4"
              >
                <div className="flex items-start gap-3">
                  <div className="font-mono text-[10px] text-[#59d6ff]">
                    {String(index + 1).padStart(2, "0")}
                  </div>

                  <div className="min-w-0">
                    <div className="text-[12px] text-[#cbd2d8]">
                      {citation.title ||
                        citation.label ||
                        citation.source ||
                        "SEC filing evidence"}
                    </div>

                    {citation.excerpt && (
                      <div className="mt-2 text-[11px] leading-5 text-[#69747e]">
                        {citation.excerpt}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <details className="mt-5 rounded-lg border border-[#1d252d] bg-[#0a0e13]">
        <summary className="cursor-pointer px-4 py-3 text-[10px] uppercase tracking-[0.16em] text-[#65717c]">
          Technical details
        </summary>

        <div className="border-t border-[#1d252d] p-4">
          {data.sql && (
            <div>
              <div className="mb-2 text-[9px] uppercase tracking-[0.16em] text-[#4f5a64]">
                SQL
              </div>

              <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-[#070a0d] p-3 font-mono text-[10px] leading-5 text-[#7e8a95]">
                {data.sql}
              </pre>
            </div>
          )}

          {data.reasoning && (
            <div className="mt-5">
              <div className="mb-2 text-[9px] uppercase tracking-[0.16em] text-[#4f5a64]">
                Reasoning
              </div>

              <div className="text-[11px] leading-5 text-[#68747f]">
                {data.reasoning}
              </div>
            </div>
          )}
        </div>
      </details>
    </motion.div>
  );
}
