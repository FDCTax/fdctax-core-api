/**
 * Authentication Context
 * Manages user authentication state across the app
 */

import { createContext, useContext, useState, useEffect } from 'react';
import { authApi } from '../lib/api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check for existing session
    const token = localStorage.getItem('access_token');
    const storedUser = localStorage.getItem('user');
    
    if (token && storedUser) {
      try {
        setUser(JSON.parse(storedUser));
      } catch (e) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
      }
    }
    setLoading(false);
  }, []);

  const login = async (email, password) => {
    const data = await authApi.login(email, password);
    
    const userData = {
      id: data.user_id,
      email: data.email,
      role: data.role,
    };
    
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('user', JSON.stringify(userData));
    setUser(userData);
    
    return userData;
  };

  const logout = () => {
    authApi.logout();
    setUser(null);
  };

  const isAuthenticated = !!user;
  const isAdmin = user?.role === 'admin';
  const isStaff = user?.role === 'staff' || user?.role === 'admin';
  const canAccessIngestion = isAdmin || isStaff || user?.role === 'tax_agent';

  return (
    <AuthContext.Provider value={{
      user,
      loading,
      login,
      logout,
      isAuthenticated,
      isAdmin,
      isStaff,
      canAccessIngestion,
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
