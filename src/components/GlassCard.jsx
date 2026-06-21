
export default function GlassCard({ children, className = "", onClick }) {
  return (
    <div 
      className={`bg-zinc-900/60 backdrop-blur-xl border border-zinc-800/80 rounded-2xl p-6 shadow-2xl transition-all duration-300 ${onClick ? 'cursor-pointer hover:border-violet-500/50 hover:bg-zinc-900/80 hover:shadow-violet-950/20' : ''} ${className}`}
      onClick={onClick}
    >
      {children}
    </div>
  );
}
