import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Typography,
  Button,
  Snackbar,
  Alert,
  Chip,
} from '@mui/material';
import {
  Refresh,
  Download,
} from '@mui/icons-material';
import SummaryCards from '../components/SummaryCards';
import DiscoveryFilters from '../components/DiscoveryFilters';
import DiscoveryTable from '../components/DiscoveryTable';
import DiscoveryDetailsDialog from '../components/DiscoveryDetailsDialog';
import { getDiscoveries, getDiscoveryById, approveDiscovery, rejectDiscovery, getStats, triggerDiscovery } from '../services/api';

const DataDiscoveryPage = () => {
  const [discoveries, setDiscoveries] = useState([]);
  const [stats, setStats] = useState({});
  const [loading, setLoading] = useState(false);
  const [pagination, setPagination] = useState({ page: 0, size: 50, total: 0, total_pages: 0 });
  
  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [environmentFilter, setEnvironmentFilter] = useState('');
  const [dataSourceFilter, setDataSourceFilter] = useState('');
  
  // Dialog state
  const [detailsDialogOpen, setDetailsDialogOpen] = useState(false);
  const [selectedDiscovery, setSelectedDiscovery] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  
  // Snackbar state
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' });
  
  // Auto-update state
  const [lastUpdateTime, setLastUpdateTime] = useState(null);
  const [newFilesCount, setNewFilesCount] = useState(0);
  const previousCountRef = useRef(0);
  const [discoveryRunning, setDiscoveryRunning] = useState(false);

  useEffect(() => {
    fetchDiscoveries();
    fetchStats();
    setLastUpdateTime(new Date());
    
    // Refresh every 30 seconds for faster updates (Airflow runs every 1 minute)
    const interval = setInterval(() => {
      fetchDiscoveries();
      fetchStats();
      setLastUpdateTime(new Date());
    }, 30000); // 30 seconds for faster updates
    
    return () => clearInterval(interval);
  }, [pagination.page, pagination.size, searchTerm, statusFilter, environmentFilter, dataSourceFilter]);
  
  // Initialize ref on first load
  useEffect(() => {
    if (pagination.total > 0 && previousCountRef.current === 0) {
      previousCountRef.current = pagination.total;
    }
  }, [pagination.total]);

  const fetchDiscoveries = async () => {
    try {
      setLoading(true);
      const previousCount = previousCountRef.current;
      const response = await getDiscoveries({
        page: pagination.page,
        size: pagination.size,
        status: statusFilter || undefined,
        environment: environmentFilter || undefined,
        data_source_type: dataSourceFilter || undefined,
        search: searchTerm || undefined,
      });
      
      const newDiscoveries = response.discoveries || [];
      const newCount = response.pagination?.total || 0;
      
      // Check if new files were added (only on first page and no filters)
      if (pagination.page === 0 && !statusFilter && !environmentFilter && !dataSourceFilter && !searchTerm) {
        if (previousCount > 0 && newCount > previousCount) {
          const addedCount = newCount - previousCount;
          setNewFilesCount(addedCount);
          showSnackbar(`${addedCount} new file(s) discovered!`, 'info');
          setTimeout(() => setNewFilesCount(0), 5000);
        }
        previousCountRef.current = newCount;
      }
      
      setDiscoveries(newDiscoveries);
      setPagination(response.pagination || pagination);
    } catch (error) {
      console.error('Error fetching discoveries:', error);
      showSnackbar('Error fetching discoveries', 'error');
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const response = await getStats();
      setStats(response);
    } catch (error) {
      console.error('Error fetching stats:', error);
    }
  };

  const handleViewDetails = async (id) => {
    try {
      setDetailsDialogOpen(true);
      setDetailsLoading(true);
      setSelectedDiscovery(null);
      
      const discovery = await getDiscoveryById(id);
      setSelectedDiscovery(discovery);
    } catch (error) {
      console.error('Error fetching discovery details:', error);
      showSnackbar('Error loading discovery details', 'error');
      setDetailsDialogOpen(false);
    } finally {
      setDetailsLoading(false);
    }
  };

  const handleApprove = async (id) => {
    try {
      await approveDiscovery(id, 'user@example.com'); // Replace with actual user
      showSnackbar('Discovery approved successfully', 'success');
      fetchDiscoveries();
      fetchStats();
    } catch (error) {
      console.error('Error approving discovery:', error);
      showSnackbar('Error approving discovery', 'error');
    }
  };

  const handleReject = async (id) => {
    try {
      await rejectDiscovery(id, 'user@example.com', 'Rejected by user'); // Replace with actual user
      showSnackbar('Discovery rejected successfully', 'success');
      fetchDiscoveries();
      fetchStats();
    } catch (error) {
      console.error('Error rejecting discovery:', error);
      showSnackbar('Error rejecting discovery', 'error');
    }
  };

  const handlePageChange = (page) => {
    setPagination({ ...pagination, page });
  };

  const handlePageSizeChange = (size) => {
    setPagination({ ...pagination, page: 0, size: parseInt(size) });
  };

  const handleClearFilters = () => {
    setSearchTerm('');
    setStatusFilter('');
    setEnvironmentFilter('');
    setDataSourceFilter('');
    setPagination({ ...pagination, page: 0 });
  };

  const showSnackbar = (message, severity = 'success') => {
    setSnackbar({ open: true, message, severity });
  };

  const handleCloseSnackbar = () => {
    setSnackbar({ ...snackbar, open: false });
  };

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Typography variant="h4" component="h1" sx={{ fontWeight: 600, fontFamily: 'Comfortaa' }}>
            Data Discovery
          </Typography>
          {lastUpdateTime && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
              <Typography variant="caption" color="text.secondary">
                Last updated: {lastUpdateTime.toLocaleTimeString()}
              </Typography>
              {newFilesCount > 0 && (
                <Chip 
                  label={`${newFilesCount} new`} 
                  color="success" 
                  size="small"
                  sx={{ height: 20, fontSize: '0.7rem' }}
                />
              )}
            </Box>
          )}
        </Box>
        <Box sx={{ display: 'flex', gap: 2 }}>
          <Button
            variant="outlined"
            startIcon={<Refresh />}
            onClick={async () => {
              try {
                // Trigger discovery first
                setDiscoveryRunning(true);
                await triggerDiscovery();
                showSnackbar('Discovery scan started. Refreshing data...', 'info');
                
                // Wait a moment for discovery to process
                await new Promise(resolve => setTimeout(resolve, 2000));
                
                // Then refresh the data
                await fetchDiscoveries();
                await fetchStats();
                setLastUpdateTime(new Date());
                previousCountRef.current = discoveries.length;
                
                // Wait a bit more and refresh again to catch new files
                setTimeout(async () => {
                  await fetchDiscoveries();
                  await fetchStats();
                  showSnackbar('Discovery complete. Data refreshed.', 'success');
                  setDiscoveryRunning(false);
                }, 5000);
              } catch (error) {
                console.error('Error triggering discovery:', error);
                showSnackbar('Error triggering discovery: ' + error.message, 'error');
                setDiscoveryRunning(false);
                // Still refresh data even if discovery fails
                fetchDiscoveries();
                fetchStats();
              }
            }}
            disabled={loading || discoveryRunning}
          >
            {discoveryRunning ? 'Scanning...' : 'Refresh'}
          </Button>
          <Button
            variant="contained"
            startIcon={<Download />}
            color="primary"
          >
            Export
          </Button>
        </Box>
      </Box>

      {/* Summary Cards */}
      <SummaryCards stats={stats} />

      {/* Filters */}
      <DiscoveryFilters
        searchTerm={searchTerm}
        onSearchChange={setSearchTerm}
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        environmentFilter={environmentFilter}
        onEnvironmentChange={setEnvironmentFilter}
        dataSourceFilter={dataSourceFilter}
        onDataSourceChange={setDataSourceFilter}
        onClearFilters={handleClearFilters}
      />

      {/* Discovery Table */}
      <DiscoveryTable
        discoveries={discoveries}
        loading={loading}
        pagination={pagination}
        onPageChange={handlePageChange}
        onPageSizeChange={handlePageSizeChange}
        onViewDetails={handleViewDetails}
        onApprove={handleApprove}
        onReject={handleReject}
      />

      {/* Details Dialog */}
      <DiscoveryDetailsDialog
        open={detailsDialogOpen}
        discovery={selectedDiscovery}
        loading={detailsLoading}
        onClose={() => {
          setDetailsDialogOpen(false);
          setSelectedDiscovery(null);
        }}
      />

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={handleCloseSnackbar}
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <Alert onClose={handleCloseSnackbar} severity={snackbar.severity} sx={{ width: '100%' }}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default DataDiscoveryPage;

