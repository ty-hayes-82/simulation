import React, { useMemo } from 'react';
import { Table, Card, Text, Badge, Flex, Button } from '@radix-ui/themes';
import { useSimulation } from '../context/SimulationContext';

export default function SimulationTable() {
  const { manifest, selectedSim, setSelectedId } = useSimulation();

  const tableData = useMemo(() => {
    if (!manifest) return [];
    
    return manifest.simulations.map(sim => ({
      id: sim.id,
      name: sim.name,
      runners: sim.meta?.runners || 0,
      orders: sim.meta?.orders || 0,
      scenario: sim.meta?.scenario || 'Unknown',
      lastModified: sim.meta?.lastModified ? new Date(sim.meta.lastModified).toLocaleDateString() : 'Unknown',
      hasHeatmap: !!sim.heatmapFilename,
      hasMetrics: !!sim.metricsFilename,
      isSelected: selectedSim?.id === sim.id
    }));
  }, [manifest, selectedSim]);

  const formatScenario = (scenario: string) => {
    return scenario.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  if (!manifest || tableData.length === 0) {
    return (
      <Card>
        <Flex align="center" justify="center" p="6">
          <Text color="gray">No simulation data available</Text>
        </Flex>
      </Card>
    );
  }

  return (
    <Card>
      <Flex direction="column" gap="3" p="4">
        <Flex align="center" justify="between">
          <Text size="4" weight="bold">Available Simulations</Text>
          <Badge color="blue" variant="soft">
            {tableData.length} simulations
          </Badge>
        </Flex>
        
        <Table.Root>
          <Table.Header>
            <Table.Row>
              <Table.ColumnHeaderCell>Name</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Runners</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Orders</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Scenario</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Last Modified</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Data</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Actions</Table.ColumnHeaderCell>
            </Table.Row>
          </Table.Header>

          <Table.Body>
            {tableData.map((row) => (
              <Table.Row 
                key={row.id}
                style={{ 
                  backgroundColor: row.isSelected ? 'var(--accent-2)' : undefined,
                  cursor: 'pointer'
                }}
                onClick={() => setSelectedId(row.id)}
              >
                <Table.RowHeaderCell>
                  <Flex direction="column" gap="1">
                    <Text size="2" weight="medium">{row.name}</Text>
                    <Text size="1" color="gray">{row.id}</Text>
                  </Flex>
                </Table.RowHeaderCell>
                
                <Table.Cell>
                  <Badge color="green" variant="soft">
                    {row.runners} {row.runners === 1 ? 'Runner' : 'Runners'}
                  </Badge>
                </Table.Cell>
                
                <Table.Cell>
                  <Badge color="orange" variant="soft">
                    {row.orders} Orders
                  </Badge>
                </Table.Cell>
                
                <Table.Cell>
                  <Text size="2">{formatScenario(row.scenario)}</Text>
                </Table.Cell>
                
                <Table.Cell>
                  <Text size="2" color="gray">{row.lastModified}</Text>
                </Table.Cell>
                
                <Table.Cell>
                  <Flex gap="1">
                    <Badge color="blue" variant={row.hasHeatmap ? 'solid' : 'outline'} size="1">
                      Heatmap
                    </Badge>
                    <Badge color="purple" variant={row.hasMetrics ? 'solid' : 'outline'} size="1">
                      Metrics
                    </Badge>
                  </Flex>
                </Table.Cell>
                
                <Table.Cell>
                  <Button 
                    size="1" 
                    variant={row.isSelected ? 'solid' : 'soft'}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedId(row.id);
                    }}
                  >
                    {row.isSelected ? 'Selected' : 'Select'}
                  </Button>
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table.Root>
      </Flex>
    </Card>
  );
}
