import { BarChart3, Brain, ClipboardCheck, FileSearch, Layers, ShieldCheck } from "lucide-react";
import { Link, Navigate } from "react-router-dom";
import BrandLogo from "../components/BrandLogo";
import { useAuth } from "../auth/AuthContext";

const featureCards = [
  {
    icon: Layers,
    title: "RCM Intake",
    text: "Upload your risk & control matrix — only a Control ID column is required. The agent normalizes it and reports field completeness.",
  },
  {
    icon: ClipboardCheck,
    title: "Adequacy Assessment",
    text: "Reconcile each control against your SOPs and monthly workpapers — misaligned frequencies and owners, and any missing workpaper months, are flagged.",
  },
  {
    icon: FileSearch,
    title: "Evidence Requirements & Intake",
    text: "Required-documents checklists generated per control, reconciled against the evidence you declare and the files you upload.",
  },
  {
    icon: ShieldCheck,
    title: "Gap Assessment",
    text: "A per-control gap picture — received vs expected, where the gap lies, severity — delivered as an Excel summary.",
  },
  {
    icon: BarChart3,
    title: "Live Visual Workspace",
    text: "Every step's results — reconciliation grids, workpaper coverage, severity rollups — update live as the agent works.",
  },
  {
    icon: Brain,
    title: "Chat-Driven, Human-in-the-Loop",
    text: "Say \"proceed\" to move to the next step, or review each step's output before you continue.",
  },
];

const Landing = () => {
  const { isAuthenticated } = useAuth();
  if (isAuthenticated) {
    return <Navigate to="/projects" replace />;
  }

  return (
    <div className="landing-page">
      <header className="landing-header">
        <div className="landing-brand">
          <BrandLogo className="kpmg-logo-img" />
          <span className="brand-separator" />
          <span className="brand-product-name">ControlAssessment</span>
        </div>
        <Link className="kpmg-btn primary" to="/login">
          Login
        </Link>
      </header>

      <main className="landing-main">
        <section className="hero-section">
          <h1>AI-Driven Control Assessment, Start to Finish</h1>
          <p>
            RCM intake, SOP &amp; workpaper adequacy, evidence requirements, and a gap assessment —
            <br />
            one guided workflow, one chat, live visualizations at every step.
          </p>
          <Link className="kpmg-btn primary large" to="/login">
            Get Started
          </Link>
        </section>

        <section className="feature-section">
          <h2>A Structured, Auditable Assessment Workflow</h2>
          <div className="feature-grid">
            {featureCards.map((item) => (
              <article key={item.title} className="feature-card">
                <div className="feature-icon">
                  <item.icon size={20} />
                </div>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
};

export default Landing;
