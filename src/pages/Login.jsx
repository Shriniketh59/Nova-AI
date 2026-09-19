import { useState } from 'react';
import { useNavigate, Link, Navigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import GlassCard from '../components/GlassCard';

export default function Login() {
  const { login, isAuthenticated, getGoogleAuthUrl } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState({});
  const [serverError, setServerError] = useState('');
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [googleNotice, setGoogleNotice] = useState('');

  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const errorParam = searchParams.get('error');

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  const validate = () => {
    const temp = {};
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    if (!email.trim()) {
      temp.email = 'Email address is required';
    } else if (!emailRegex.test(email.trim())) {
      temp.email = 'Please enter a valid email address';
    }

    if (!password) {
      temp.password = 'Password is required';
    } else if (password.length < 6) {
      temp.password = 'Password must be at least 6 characters';
    }

    setErrors(temp);
    return Object.keys(temp).length === 0;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setServerError('');
    setGoogleNotice('');
    if (!validate()) return;

    setLoading(true);
    const result = await login(email.trim(), password);
    setLoading(false);

    if (result.success) {
      navigate('/');
    } else {
      setServerError(result.error || 'Invalid credentials');
    }
  };

  const handleGoogleLogin = async () => {
    setGoogleLoading(true);
    setServerError('');
    setGoogleNotice('');
    try {
      const config = await getGoogleAuthUrl();
      if (config.configured && config.url) {
        window.location.href = config.url;
      } else {
        setGoogleNotice(
          config.message ||
            'Google OAuth requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env. Use Email + Password to sign in.'
        );
      }
    } catch (err) {
      setGoogleNotice('Failed to initialize Google authentication');
    } finally {
      setGoogleLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950 p-6 relative overflow-hidden">
      {/* Ambient background glows */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-violet-600/10 rounded-full blur-3xl -z-10 animate-pulse"></div>
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-fuchsia-600/10 rounded-full blur-3xl -z-10 animate-pulse delay-700"></div>

      <GlassCard className="w-full max-w-md space-y-6 p-8 border border-zinc-800/80 bg-zinc-900/50 backdrop-blur-2xl shadow-2xl rounded-2xl">
        {/* Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex w-12 h-12 items-center justify-center mb-1">
            <img src="/logo.png" alt="Nova AI" className="w-full h-full object-contain" />
          </div>
          <h2 className="text-2xl font-extrabold text-white tracking-tight">Sign in to Nova AI</h2>
          <p className="text-sm text-zinc-400">Access your private multi-agent research workspace</p>
        </div>

        {/* Server & OAuth error banners */}
        {errorParam && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-rose-400 text-xs font-medium flex items-center space-x-2">
            <span>⚠️</span>
            <span>Authentication failed: {errorParam}</span>
          </div>
        )}

        {serverError && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-rose-400 text-xs font-medium flex items-center space-x-2">
            <span>⚠️</span>
            <span>{serverError}</span>
          </div>
        )}

        {googleNotice && (
          <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl text-amber-300 text-xs font-medium flex items-start space-x-2">
            <span className="mt-0.5">ℹ️</span>
            <span>{googleNotice}</span>
          </div>
        )}

        {/* Google OAuth Button */}
        <button
          type="button"
          onClick={handleGoogleLogin}
          disabled={googleLoading}
          className="w-full py-3 px-4 rounded-xl border border-zinc-750 bg-zinc-850/60 hover:bg-zinc-800 hover:border-zinc-700 text-zinc-200 text-sm font-semibold transition-all duration-200 flex items-center justify-center space-x-3 shadow-sm hover:shadow"
        >
          {googleLoading ? (
            <div className="w-4 h-4 border-2 border-zinc-400 border-t-transparent rounded-full animate-spin"></div>
          ) : (
            <svg className="w-4 h-4" viewBox="0 0 24 24">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
              />
            </svg>
          )}
          <span>Continue with Google</span>
        </button>

        {/* Divider */}
        <div className="flex items-center space-x-3 text-xs text-zinc-500 uppercase tracking-wider font-semibold">
          <div className="flex-1 h-px bg-zinc-800"></div>
          <span>or continue with email</span>
          <div className="flex-1 h-px bg-zinc-800"></div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          {/* Email */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-zinc-400">Email Address</label>
            <div className="relative">
              <input
                type="email"
                placeholder="name@organization.com"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (errors.email) setErrors({ ...errors, email: '' });
                }}
                className={`w-full bg-zinc-900/90 border ${
                  errors.email ? 'border-rose-500 focus:border-rose-500' : 'border-zinc-800 focus:border-violet-500'
                } rounded-xl pl-3.5 pr-10 py-2.5 text-sm text-white placeholder-zinc-500 outline-none transition-colors`}
              />
              <span className="absolute right-3.5 top-3 text-zinc-500 pointer-events-none">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16 12a4 4 0 10-8 0 4 4 0 008 0zm0 0v1.5a2.5 2.5 0 005 0V12a9 9 0 10-9 9m4.5-1.206a8.959 8.959 0 01-4.5 1.206" />
                </svg>
              </span>
            </div>
            {errors.email && <p className="text-xs text-rose-400 font-medium">{errors.email}</p>}
          </div>

          {/* Password */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-semibold text-zinc-400">Password</label>
              <Link
                to="/forgot-password"
                className="text-xs text-violet-400 hover:text-violet-300 font-medium transition-colors"
              >
                Forgot password?
              </Link>
            </div>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                placeholder="••••••••"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (errors.password) setErrors({ ...errors, password: '' });
                }}
                className={`w-full bg-zinc-900/90 border ${
                  errors.password ? 'border-rose-500 focus:border-rose-500' : 'border-zinc-800 focus:border-violet-500'
                } rounded-xl pl-3.5 pr-10 py-2.5 text-sm text-white placeholder-zinc-500 outline-none transition-colors`}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3.5 top-3 text-zinc-500 hover:text-zinc-300 transition-colors"
                title={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                )}
              </button>
            </div>
            {errors.password && <p className="text-xs text-rose-400 font-medium">{errors.password}</p>}
          </div>

          {/* Submit */}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 hover:from-violet-500 hover:to-fuchsia-500 disabled:opacity-50 font-semibold text-sm text-white shadow-lg shadow-violet-500/20 transition-all duration-200 flex items-center justify-center space-x-2 mt-2"
          >
            {loading ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                <span>Signing in...</span>
              </>
            ) : (
              <span>Sign In</span>
            )}
          </button>
        </form>

        {/* Footer */}
        <div className="text-center text-xs text-zinc-400 pt-2">
          <span>Don't have an account? </span>
          <Link to="/signup" className="text-violet-400 hover:text-violet-300 font-semibold transition-colors">
            Sign Up
          </Link>
        </div>
      </GlassCard>
    </div>
  );
}
