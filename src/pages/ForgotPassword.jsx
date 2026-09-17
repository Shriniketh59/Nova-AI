import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import GlassCard from '../components/GlassCard';

export default function ForgotPassword() {
  const { forgotPassword, resetPassword } = useAuth();
  const [searchParams] = useSearchParams();
  const queryToken = searchParams.get('token') || '';

  const [step, setStep] = useState(queryToken ? 'reset' : 'request'); // 'request' | 'reset' | 'done'
  const [email, setEmail] = useState('');
  const [token, setToken] = useState(queryToken);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [generatedToken, setGeneratedToken] = useState('');

  const navigate = useNavigate();

  const handleRequestSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setMessage('');
    if (!email.trim()) {
      setError('Please enter your email address');
      return;
    }

    setLoading(true);
    const result = await forgotPassword(email.trim());
    setLoading(false);

    if (result.success) {
      setMessage(result.data?.message || 'Password reset link generated.');
      if (result.data?.reset_token) {
        setGeneratedToken(result.data.reset_token);
        setToken(result.data.reset_token);
      }
    } else {
      setError(result.error || 'Failed to process request');
    }
  };

  const handleResetSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setMessage('');

    if (!token.trim()) {
      setError('Reset token is required');
      return;
    }

    if (!newPassword || newPassword.length < 6) {
      setError('New password must be at least 6 characters');
      return;
    }

    if (newPassword !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    setLoading(true);
    const result = await resetPassword(token.trim(), newPassword);
    setLoading(false);

    if (result.success) {
      setStep('done');
      setMessage(result.message || 'Password reset successfully!');
    } else {
      setError(result.error || 'Failed to reset password');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950 p-6 relative overflow-hidden">
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-violet-600/10 rounded-full blur-3xl -z-10 animate-pulse"></div>
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-fuchsia-600/10 rounded-full blur-3xl -z-10 animate-pulse delay-700"></div>

      <GlassCard className="w-full max-w-md space-y-6 p-8 border border-zinc-800/80 bg-zinc-900/50 backdrop-blur-2xl shadow-2xl rounded-2xl">
        {/* Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex w-12 h-12 items-center justify-center mb-1">
            <img src="/logo.png" alt="Nova AI" className="w-full h-full object-contain" />
          </div>
          <h2 className="text-2xl font-extrabold text-white tracking-tight">Reset Password</h2>
          <p className="text-sm text-zinc-400">
            {step === 'request' && 'Enter your email to receive recovery instructions'}
            {step === 'reset' && 'Set a new password for your Nova AI account'}
            {step === 'done' && 'Your account security has been restored'}
          </p>
        </div>

        {error && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-rose-400 text-xs font-medium flex items-center space-x-2">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {message && (
          <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-emerald-400 text-xs font-medium flex items-center space-x-2">
            <span>✅</span>
            <span>{message}</span>
          </div>
        )}

        {/* STEP 1: Request Reset */}
        {step === 'request' && (
          <form onSubmit={handleRequestSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-zinc-400">Email Address</label>
              <input
                type="email"
                placeholder="name@organization.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-zinc-900/90 border border-zinc-800 focus:border-violet-500 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-zinc-500 outline-none transition-colors"
              />
            </div>

            {generatedToken && (
              <div className="p-4 bg-violet-950/40 border border-violet-800/40 rounded-xl space-y-2">
                <div className="flex items-center justify-between text-xs text-violet-300 font-semibold">
                  <span>Development Token Generated</span>
                  <button
                    type="button"
                    onClick={() => setStep('reset')}
                    className="text-xs text-white underline font-bold hover:text-violet-200"
                  >
                    Proceed to Reset →
                  </button>
                </div>
                <p className="text-[11px] font-mono text-zinc-400 break-all bg-zinc-900/80 p-2 rounded border border-zinc-800">
                  {generatedToken}
                </p>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 hover:from-violet-500 hover:to-fuchsia-500 disabled:opacity-50 font-semibold text-sm text-white shadow-lg shadow-violet-500/20 transition-all duration-200 flex items-center justify-center space-x-2"
            >
              {loading ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  <span>Generating Link...</span>
                </>
              ) : (
                <span>Generate Reset Link</span>
              )}
            </button>

            <div className="text-center text-xs text-zinc-400 pt-2 flex items-center justify-between">
              <Link to="/login" className="text-violet-400 hover:text-violet-300 font-semibold transition-colors">
                ← Back to Login
              </Link>
              <button
                type="button"
                onClick={() => setStep('reset')}
                className="text-zinc-500 hover:text-zinc-400 font-medium"
              >
                Already have a token?
              </button>
            </div>
          </form>
        )}

        {/* STEP 2: Enter Token & New Password */}
        {step === 'reset' && (
          <form onSubmit={handleResetSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-zinc-400">Reset Token</label>
              <input
                type="text"
                placeholder="Paste reset token"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                className="w-full bg-zinc-900/90 border border-zinc-800 focus:border-violet-500 rounded-xl px-3.5 py-2.5 text-sm text-white font-mono placeholder-zinc-500 outline-none transition-colors"
              />
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-zinc-400">New Password</label>
              <input
                type="password"
                placeholder="At least 6 characters"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="w-full bg-zinc-900/90 border border-zinc-800 focus:border-violet-500 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-zinc-500 outline-none transition-colors"
              />
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-zinc-400">Confirm New Password</label>
              <input
                type="password"
                placeholder="Re-enter new password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full bg-zinc-900/90 border border-zinc-800 focus:border-violet-500 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-zinc-500 outline-none transition-colors"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 hover:from-violet-500 hover:to-fuchsia-500 disabled:opacity-50 font-semibold text-sm text-white shadow-lg shadow-violet-500/20 transition-all duration-200 flex items-center justify-center space-x-2"
            >
              {loading ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  <span>Updating Password...</span>
                </>
              ) : (
                <span>Update Password</span>
              )}
            </button>

            <div className="text-center text-xs text-zinc-400 pt-2 flex items-center justify-between">
              <button
                type="button"
                onClick={() => setStep('request')}
                className="text-zinc-500 hover:text-zinc-400 font-medium"
              >
                ← Request New Token
              </button>
              <Link to="/login" className="text-violet-400 hover:text-violet-300 font-semibold transition-colors">
                Back to Login
              </Link>
            </div>
          </form>
        )}

        {/* STEP 3: Completed */}
        {step === 'done' && (
          <div className="space-y-5 text-center">
            <div className="w-12 h-12 bg-emerald-500/10 border border-emerald-500/30 rounded-full flex items-center justify-center mx-auto text-emerald-400 text-xl">
              ✓
            </div>
            <p className="text-sm text-zinc-300">
              Your password has been successfully updated. You can now sign in using your new credentials.
            </p>
            <button
              type="button"
              onClick={() => navigate('/login')}
              className="w-full py-3 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 hover:from-violet-500 hover:to-fuchsia-500 font-semibold text-sm text-white shadow-lg shadow-violet-500/20 transition-all duration-200"
            >
              Sign In Now
            </button>
          </div>
        )}
      </GlassCard>
    </div>
  );
}
