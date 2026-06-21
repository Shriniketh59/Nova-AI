// Mock API Service for Nova AI Research Platform

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const MOCK_PAPERS = [
  {
    id: "1",
    title: "Quantum Neural Decoupling in Deep Learning Architectures",
    authors: "Dr. Elena Rostova, Prof. Alan Turing",
    abstract: "We propose a novel decoupling mechanism for quantum neural network layers. By introducing multi-dimensional entanglement gates, we demonstrate a 40% reduction in training latency for complex transformers.",
    tags: ["Quantum Computing", "Deep Learning", "Transformers"],
    date: "2026-05-12",
    citations: 24,
    rating: 4.8
  },
  {
    id: "2",
    title: "Synthesizing Bio-compatible Nanostructures via Reinforcement Learning",
    authors: "Dr. Kenji Sato, Dr. Sarah Jenkins",
    abstract: "An AI-guided synthesis pipeline is developed for target nanostructures. The model uses reward shaping based on biological compatibility simulations to optimize chemical path discovery.",
    tags: ["Nanotechnology", "Reinforcement Learning", "Bio-medical"],
    date: "2026-06-02",
    citations: 12,
    rating: 4.5
  },
  {
    id: "3",
    title: "Zero-Shot Cross-Lingual Knowledge Transfer in Medical Diagnosis",
    authors: "Prof. Maria Silva, Dr. Rajesh Kumar",
    abstract: "We evaluate large language models on diagnostic report generation in low-resource languages. Our framework achieves high precision without requiring local translated training corpuses.",
    tags: ["NLP", "Healthcare", "Zero-Shot Transfer"],
    date: "2026-06-15",
    citations: 8,
    rating: 4.9
  }
];

export const searchPapers = async (query = "") => {
  await delay(600); // Simulate API latency
  if (!query) return MOCK_PAPERS;
  const lowerQuery = query.toLowerCase();
  return MOCK_PAPERS.filter(
    (paper) =>
      paper.title.toLowerCase().includes(lowerQuery) ||
      paper.abstract.toLowerCase().includes(lowerQuery) ||
      paper.tags.some((tag) => tag.toLowerCase().includes(lowerQuery))
  );
};

export const getPaperById = async (id) => {
  await delay(300);
  return MOCK_PAPERS.find((p) => p.id === id) || null;
};

export const analyzePaperReview = async () => {
  await delay(1500); // Simulate heavy AI reasoning
  
  const scores = {
    novelty: Math.floor(Math.random() * 3) + 8, // 8-10
    methodology: Math.floor(Math.random() * 4) + 7, // 7-10
    clarity: Math.floor(Math.random() * 3) + 8, // 8-10
  };
  
  const overall = parseFloat(((scores.novelty + scores.methodology + scores.clarity) / 3).toFixed(1));

  return {
    success: true,
    overallScore: overall,
    scores,
    analysis: [
      "The methodology shows strong theoretical foundations, particularly in the validation setup.",
      "The novelty is excellent; combining these fields solves a long-standing constraint in computational limits.",
      "Clarity could be improved in Section 3 by elaborating on the dataset distribution details."
    ],
    recommendation: overall >= 8.5 ? "Strong Accept" : "Accept with Minor Revisions",
    timestamp: new Date().toISOString()
  };
};
