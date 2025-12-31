/**
 * Bookkeeping Ingestion Page
 * Multi-step wizard for importing bank transactions
 */

import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { ingestionApi } from '../lib/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { Progress } from '../components/ui/progress';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Checkbox } from '../components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { 
  Upload, 
  FileSpreadsheet, 
  ArrowRight, 
  Check, 
  AlertCircle, 
  Loader2,
  RefreshCw,
  History,
  LogOut,
  ChevronLeft,
  Download,
  Trash2
} from 'lucide-react';

// Wizard steps
const STEPS = {
  UPLOAD: 'upload',
  MAPPING: 'mapping',
  IMPORT: 'import',
  COMPLETE: 'complete',
};

// Status badge variants
const STATUS_VARIANTS = {
  pending: 'secondary',
  processing: 'default',
  completed: 'default',
  failed: 'destructive',
  rolled_back: 'outline',
};

export default function Ingestion() {
  const { user, logout, isStaff } = useAuth();
  
  // Wizard state
  const [step, setStep] = useState(STEPS.UPLOAD);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  
  // Upload state
  const [file, setFile] = useState(null);
  const [clientId, setClientId] = useState('');
  const [dragActive, setDragActive] = useState(false);
  
  // Parse state
  const [batchId, setBatchId] = useState('');
  const [parseData, setParseData] = useState(null);
  const [columnMapping, setColumnMapping] = useState({});
  const [skipDuplicates, setSkipDuplicates] = useState(true);
  
  // Import state
  const [importProgress, setImportProgress] = useState(0);
  const [importResult, setImportResult] = useState(null);
  
  // Batch history
  const [batches, setBatches] = useState([]);
  const [batchesLoading, setBatchesLoading] = useState(false);
  const [selectedBatch, setSelectedBatch] = useState(null);
  const [showRollbackDialog, setShowRollbackDialog] = useState(false);
  const [rollbackLoading, setRollbackLoading] = useState(false);

  // Transaction fields for mapping
  const TRANSACTION_FIELDS = [
    { key: 'date', label: 'Date', required: true },
    { key: 'amount', label: 'Amount', required: true },
    { key: 'description', label: 'Description', required: false },
    { key: 'payee', label: 'Payee/Merchant', required: false },
    { key: 'category', label: 'Category', required: false },
  ];

  // Load batches on mount
  const loadBatches = useCallback(async () => {
    setBatchesLoading(true);
    try {
      const data = await ingestionApi.listBatches({ limit: 50 });
      setBatches(data);
    } catch (err) {
      console.error('Failed to load batches:', err);
    } finally {
      setBatchesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBatches();
  }, [loadBatches]);

  // File drag handlers
  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = (selectedFile) => {
    const ext = selectedFile.name.split('.').pop().toLowerCase();
    if (!['csv', 'xlsx', 'xls'].includes(ext)) {
      setError('Please select a CSV or Excel file (.csv, .xlsx, .xls)');
      return;
    }
    setFile(selectedFile);
    setError('');
  };

  // Step 1: Upload file
  const handleUpload = async () => {
    if (!file || !clientId.trim()) {
      setError('Please select a file and enter a client ID');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const uploadResult = await ingestionApi.uploadFile(file, clientId.trim());
      setBatchId(uploadResult.batch_id);
      
      // Automatically parse
      const parseResult = await ingestionApi.parseFile(uploadResult.batch_id);
      setParseData(parseResult);
      
      // Apply suggested mappings
      setColumnMapping(parseResult.mapping_suggestions || {});
      
      setStep(STEPS.MAPPING);
    } catch (err) {
      const message = err.response?.data?.detail || 'Upload failed. Please try again.';
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  // Step 2: Import with mapping
  const handleImport = async () => {
    // Validate required mappings
    if (!columnMapping.date || !columnMapping.amount) {
      setError('Please map the required Date and Amount columns');
      return;
    }

    setLoading(true);
    setError('');
    setImportProgress(30);

    try {
      setImportProgress(50);
      const result = await ingestionApi.importTransactions(batchId, columnMapping, skipDuplicates);
      setImportProgress(100);
      setImportResult(result);
      setStep(STEPS.COMPLETE);
      loadBatches(); // Refresh batch list
    } catch (err) {
      const message = err.response?.data?.detail || 'Import failed. Please try again.';
      setError(message);
      setImportProgress(0);
    } finally {
      setLoading(false);
    }
  };

  // Rollback batch
  const handleRollback = async () => {
    if (!selectedBatch) return;
    
    setRollbackLoading(true);
    try {
      await ingestionApi.rollbackBatch(selectedBatch.id);
      setShowRollbackDialog(false);
      setSelectedBatch(null);
      loadBatches();
    } catch (err) {
      const message = err.response?.data?.detail || 'Rollback failed';
      setError(message);
    } finally {
      setRollbackLoading(false);
    }
  };

  // Reset wizard
  const resetWizard = () => {
    setStep(STEPS.UPLOAD);
    setFile(null);
    setClientId('');
    setBatchId('');
    setParseData(null);
    setColumnMapping({});
    setImportResult(null);
    setImportProgress(0);
    setError('');
  };

  // Format date for display
  const formatDate = (dateStr) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString();
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100" data-testid="ingestion-page">
      {/* Header */}
      <header className="border-b bg-white/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-3">
              <FileSpreadsheet className="h-6 w-6 text-primary" />
              <h1 className="text-lg font-semibold">Bookkeeping Ingestion</h1>
            </div>
            <div className="flex items-center gap-4">
              <span className="text-sm text-muted-foreground">{user?.email}</span>
              <Badge variant="outline">{user?.role}</Badge>
              <Button variant="ghost" size="sm" onClick={logout} data-testid="logout-btn">
                <LogOut className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Tabs defaultValue="import" className="space-y-6">
          <TabsList>
            <TabsTrigger value="import" data-testid="tab-import">
              <Upload className="h-4 w-4 mr-2" />
              Import
            </TabsTrigger>
            <TabsTrigger value="history" data-testid="tab-history">
              <History className="h-4 w-4 mr-2" />
              History
            </TabsTrigger>
          </TabsList>

          {/* Import Tab */}
          <TabsContent value="import" className="space-y-6">
            {/* Progress Steps */}
            <div className="flex items-center justify-center gap-2 py-4">
              {[
                { key: STEPS.UPLOAD, label: 'Upload' },
                { key: STEPS.MAPPING, label: 'Map Columns' },
                { key: STEPS.IMPORT, label: 'Import' },
                { key: STEPS.COMPLETE, label: 'Complete' },
              ].map((s, i) => (
                <div key={s.key} className="flex items-center">
                  <div className={`
                    flex items-center justify-center w-8 h-8 rounded-full text-sm font-medium
                    ${step === s.key ? 'bg-primary text-primary-foreground' : 
                      Object.values(STEPS).indexOf(step) > Object.values(STEPS).indexOf(s.key)
                        ? 'bg-green-500 text-white' : 'bg-muted text-muted-foreground'}
                  `}>
                    {Object.values(STEPS).indexOf(step) > Object.values(STEPS).indexOf(s.key) 
                      ? <Check className="h-4 w-4" /> 
                      : i + 1}
                  </div>
                  <span className="ml-2 text-sm hidden sm:inline">{s.label}</span>
                  {i < 3 && <ArrowRight className="h-4 w-4 mx-3 text-muted-foreground" />}
                </div>
              ))}
            </div>

            {/* Error Display */}
            {error && (
              <div className="flex items-center gap-2 p-4 text-red-600 bg-red-50 border border-red-200 rounded-lg" data-testid="error-message">
                <AlertCircle className="h-5 w-5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {/* Step 1: Upload */}
            {step === STEPS.UPLOAD && (
              <Card data-testid="upload-step">
                <CardHeader>
                  <CardTitle>Upload Bank Statement</CardTitle>
                  <CardDescription>
                    Upload a CSV or Excel file containing bank transactions
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="space-y-2">
                    <Label htmlFor="client-id">Client ID *</Label>
                    <Input
                      id="client-id"
                      placeholder="Enter client ID (e.g., client-001)"
                      value={clientId}
                      onChange={(e) => setClientId(e.target.value)}
                      data-testid="client-id-input"
                    />
                  </div>

                  <div
                    className={`
                      border-2 border-dashed rounded-lg p-8 text-center transition-colors
                      ${dragActive ? 'border-primary bg-primary/5' : 'border-muted-foreground/25'}
                      ${file ? 'bg-green-50 border-green-300' : ''}
                    `}
                    onDragEnter={handleDrag}
                    onDragLeave={handleDrag}
                    onDragOver={handleDrag}
                    onDrop={handleDrop}
                    data-testid="file-dropzone"
                  >
                    {file ? (
                      <div className="space-y-2">
                        <Check className="h-12 w-12 mx-auto text-green-500" />
                        <p className="font-medium">{file.name}</p>
                        <p className="text-sm text-muted-foreground">
                          {(file.size / 1024).toFixed(1)} KB
                        </p>
                        <Button variant="outline" size="sm" onClick={() => setFile(null)}>
                          Change File
                        </Button>
                      </div>
                    ) : (
                      <div className="space-y-4">
                        <Upload className="h-12 w-12 mx-auto text-muted-foreground" />
                        <div>
                          <p className="font-medium">Drag and drop your file here</p>
                          <p className="text-sm text-muted-foreground">or click to browse</p>
                        </div>
                        <input
                          type="file"
                          accept=".csv,.xlsx,.xls"
                          onChange={(e) => e.target.files[0] && handleFileSelect(e.target.files[0])}
                          className="hidden"
                          id="file-input"
                          data-testid="file-input"
                        />
                        <Button variant="outline" asChild>
                          <label htmlFor="file-input" className="cursor-pointer">
                            Browse Files
                          </label>
                        </Button>
                        <p className="text-xs text-muted-foreground">
                          Supported: CSV, Excel (.xlsx, .xls) • Max 50MB
                        </p>
                      </div>
                    )}
                  </div>

                  <div className="flex justify-end">
                    <Button 
                      onClick={handleUpload} 
                      disabled={!file || !clientId.trim() || loading}
                      data-testid="upload-btn"
                    >
                      {loading ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Uploading...
                        </>
                      ) : (
                        <>
                          Upload & Parse
                          <ArrowRight className="h-4 w-4" />
                        </>
                      )}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Step 2: Column Mapping */}
            {step === STEPS.MAPPING && parseData && (
              <Card data-testid="mapping-step">
                <CardHeader>
                  <CardTitle>Map Columns</CardTitle>
                  <CardDescription>
                    Match your file columns to transaction fields.
                    {parseData.detected_format && (
                      <Badge variant="secondary" className="ml-2">
                        Detected: {parseData.detected_format.toUpperCase()} format
                      </Badge>
                    )}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  {/* Column Mapping */}
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {TRANSACTION_FIELDS.map((field) => (
                      <div key={field.key} className="space-y-2">
                        <Label>
                          {field.label} {field.required && <span className="text-red-500">*</span>}
                        </Label>
                        <Select
                          value={columnMapping[field.key] || 'none'}
                          onValueChange={(value) => 
                            setColumnMapping(prev => ({ 
                              ...prev, 
                              [field.key]: value === 'none' ? undefined : value 
                            }))
                          }
                        >
                          <SelectTrigger data-testid={`mapping-${field.key}`}>
                            <SelectValue placeholder="Select column" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">-- Not mapped --</SelectItem>
                            {parseData.columns.map((col) => (
                              <SelectItem key={col} value={col}>{col}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    ))}
                  </div>

                  {/* Skip Duplicates Option */}
                  <div className="flex items-center space-x-2">
                    <Checkbox
                      id="skip-duplicates"
                      checked={skipDuplicates}
                      onCheckedChange={setSkipDuplicates}
                      data-testid="skip-duplicates-checkbox"
                    />
                    <Label htmlFor="skip-duplicates" className="text-sm font-normal">
                      Skip duplicate transactions (recommended)
                    </Label>
                  </div>

                  {/* Data Preview */}
                  <div className="space-y-2">
                    <Label>Preview ({parseData.row_count} rows total)</Label>
                    <div className="border rounded-lg overflow-auto max-h-64">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            {parseData.columns.map((col) => (
                              <TableHead key={col} className="whitespace-nowrap">{col}</TableHead>
                            ))}
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {parseData.preview.slice(0, 5).map((row, i) => (
                            <TableRow key={i}>
                              {parseData.columns.map((col) => (
                                <TableCell key={col} className="whitespace-nowrap">
                                  {row[col]?.toString() || '-'}
                                </TableCell>
                              ))}
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </div>

                  <div className="flex justify-between">
                    <Button variant="outline" onClick={resetWizard} data-testid="back-btn">
                      <ChevronLeft className="h-4 w-4" />
                      Start Over
                    </Button>
                    <Button 
                      onClick={handleImport} 
                      disabled={!columnMapping.date || !columnMapping.amount || loading}
                      data-testid="import-btn"
                    >
                      {loading ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Importing...
                        </>
                      ) : (
                        <>
                          Import {parseData.row_count} Transactions
                          <ArrowRight className="h-4 w-4" />
                        </>
                      )}
                    </Button>
                  </div>

                  {loading && (
                    <Progress value={importProgress} className="h-2" />
                  )}
                </CardContent>
              </Card>
            )}

            {/* Step 3: Complete */}
            {step === STEPS.COMPLETE && importResult && (
              <Card data-testid="complete-step">
                <CardHeader className="text-center">
                  <div className="mx-auto w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mb-4">
                    <Check className="h-8 w-8 text-green-600" />
                  </div>
                  <CardTitle>Import Complete!</CardTitle>
                  <CardDescription>
                    Your transactions have been successfully imported
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="grid grid-cols-3 gap-4 text-center">
                    <div className="p-4 bg-green-50 rounded-lg">
                      <p className="text-3xl font-bold text-green-600" data-testid="imported-count">
                        {importResult.imported_count}
                      </p>
                      <p className="text-sm text-muted-foreground">Imported</p>
                    </div>
                    <div className="p-4 bg-yellow-50 rounded-lg">
                      <p className="text-3xl font-bold text-yellow-600" data-testid="skipped-count">
                        {importResult.skipped_duplicates}
                      </p>
                      <p className="text-sm text-muted-foreground">Skipped (Duplicates)</p>
                    </div>
                    <div className="p-4 bg-red-50 rounded-lg">
                      <p className="text-3xl font-bold text-red-600" data-testid="error-count">
                        {importResult.error_count}
                      </p>
                      <p className="text-sm text-muted-foreground">Errors</p>
                    </div>
                  </div>

                  {importResult.errors?.length > 0 && (
                    <div className="space-y-2">
                      <Label>Errors</Label>
                      <div className="border rounded-lg p-4 max-h-40 overflow-auto bg-red-50">
                        {importResult.errors.map((err, i) => (
                          <p key={i} className="text-sm text-red-600">
                            Row {err.row}: {err.error}
                          </p>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="flex justify-center">
                    <Button onClick={resetWizard} data-testid="new-import-btn">
                      <Upload className="h-4 w-4" />
                      Import Another File
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* History Tab */}
          <TabsContent value="history" className="space-y-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle>Import History</CardTitle>
                  <CardDescription>View and manage past imports</CardDescription>
                </div>
                <Button variant="outline" size="sm" onClick={loadBatches} disabled={batchesLoading}>
                  <RefreshCw className={`h-4 w-4 ${batchesLoading ? 'animate-spin' : ''}`} />
                </Button>
              </CardHeader>
              <CardContent>
                {batchesLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : batches.length === 0 ? (
                  <div className="text-center py-8 text-muted-foreground">
                    <History className="h-12 w-12 mx-auto mb-2 opacity-50" />
                    <p>No import history yet</p>
                  </div>
                ) : (
                  <div className="border rounded-lg overflow-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>File</TableHead>
                          <TableHead>Client</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead className="text-right">Imported</TableHead>
                          <TableHead className="text-right">Skipped</TableHead>
                          <TableHead>Uploaded</TableHead>
                          <TableHead>Actions</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {batches.map((batch) => (
                          <TableRow key={batch.id} data-testid={`batch-row-${batch.id}`}>
                            <TableCell className="font-medium max-w-[200px] truncate">
                              {batch.file_name}
                            </TableCell>
                            <TableCell>{batch.client_id}</TableCell>
                            <TableCell>
                              <Badge variant={STATUS_VARIANTS[batch.status] || 'secondary'}>
                                {batch.status}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-right">{batch.imported_count}</TableCell>
                            <TableCell className="text-right">{batch.skipped_count}</TableCell>
                            <TableCell className="text-sm text-muted-foreground">
                              {formatDate(batch.uploaded_at)}
                            </TableCell>
                            <TableCell>
                              {batch.status === 'completed' && isStaff && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => {
                                    setSelectedBatch(batch);
                                    setShowRollbackDialog(true);
                                  }}
                                  data-testid={`rollback-btn-${batch.id}`}
                                >
                                  <Trash2 className="h-4 w-4 text-destructive" />
                                </Button>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        {/* Rollback Confirmation Dialog */}
        <Dialog open={showRollbackDialog} onOpenChange={setShowRollbackDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Confirm Rollback</DialogTitle>
              <DialogDescription>
                This will delete all {selectedBatch?.imported_count} transactions imported from "{selectedBatch?.file_name}". This action cannot be undone.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setShowRollbackDialog(false)}>
                Cancel
              </Button>
              <Button 
                variant="destructive" 
                onClick={handleRollback}
                disabled={rollbackLoading}
                data-testid="confirm-rollback-btn"
              >
                {rollbackLoading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Rolling back...
                  </>
                ) : (
                  'Rollback Import'
                )}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </main>
    </div>
  );
}
