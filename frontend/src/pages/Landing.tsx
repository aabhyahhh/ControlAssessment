import { BarChart3, Brain, ClipboardCheck, FileSearch, Layers, ShieldCheck } from "lucide-react";
import { Link, Navigate } from "react-router-dom";
import BrandLogo from "../components/BrandLogo";
import { useAuth } from "../auth/AuthContext";

const featureCards = [
  {
    icon: Layers,
    title: "RACM Validation",
    text: "Upload your risk & control matrix — the agent normalizes it, checks completeness, and prioritizes by risk.",
  },
  {
    icon: FileSearch,
    title: "Evidence Gap Detection",
    text: "Required-documents checklists generated per control, validated against what you actually uploaded.",
  },
  {
    icon: ClipboardCheck,
    title: "SOP-Based Adequacy",
    text: "Compare control design against your SOP — catch misaligned frequencies, owners, and coverage gaps.",
  },
  {
    icon: ShieldCheck,
    title: "Control Effectiveness",
    text: "Generate testing attributes and run sample-based control testing, just like a real TOE engagement.",
  },
  {
    icon: BarChart3,
    title: "Live Visual Workspace",
    text: "Every phase's results — heatmaps, gauges, donuts, priority queues — update live as the agent works.",
  },
  {
    icon: Brain,
    title: "Human-in-the-Loop AI",
    text: "Every inferred field and generated attribute is reviewable and editable before it's ever relied on.",
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
            RACM validation, evidence review, SOP-based adequacy, and control effectiveness testing —
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
