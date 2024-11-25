import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy import stats
import seaborn as sns
import io
import openpyxl

# Custom color schemes
COLOR_SCHEMES = {
    'main': ['#003f5c', '#58508d', '#bc5090', '#ff6361', '#ffa600'],
    'focus': ['#ff6361', '#ffa600', '#003f5c', '#58508d', '#bc5090'],
    'background': ['#f5f5f5', '#e0e0e0'],
    'highlights': ['#ff6361', '#ffa600'],
    'lowlights': ['#003f5c', '#58508d']
}

# Page configuration
st.set_page_config(
    page_title="Queensland Energy & Emissions Analysis",
    page_icon="🌏",
    layout="wide",
    initial_sidebar_state="expanded"
)

def create_excel_download(df, ef_electricity, ef_fuel):
    """Create Excel file for download"""
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Main data sheet
        df.to_excel(writer, sheet_name='Energy Data', index=False)
        
        # Emission factors
        ef_electricity.to_excel(writer, sheet_name='Electricity Factors', index=False)
        ef_fuel.to_excel(writer, sheet_name='Fuel Factors', index=False)
        
        # Results summary
        pd.DataFrame({
            'Metric': ['Scope 1 Total', 'Scope 2 Total', 'Renewable Total'],
        }).to_excel(writer, sheet_name='Results Summary', index=False)
    
    return output.getvalue()

@st.cache_data
def load_data():
    """Load and process all datasets"""
    try:
        # Load raw data
        df = pd.read_csv('df.csv')
        df = df[(df['Industry']!="All Industries") & (df['Jurisdiction'] != 'AUS')]
        ef_electricity = pd.read_csv('ef_electricity.csv')
        ef_fuel = pd.read_csv('ef_fuel.csv')
        
        # Process emission factors
        electricity_factors = {
            'Year': ef_electricity['Year'].values[0],
            'EF_tCO2e_PJ': ef_electricity['EF_tCO2e_PJ_electricity'].values[0],
            'EF_KgCO2e_GJ': ef_electricity['EF_KgCO2e_GJ_electricity'].values[0],
            'EF_KgCO2e_kWh': ef_electricity['EF_KgCO2e_kWh_electricity'].values[0]
        }
        
        fuel_factors = ef_fuel.set_index('Energy_type')[['EF_tCO2e_PJ', 'EF_KgCO2e_GJ_NGA_23']].to_dict('index')
        
        # Create focused datasets
        df_qld_focus = df[(df['Jurisdiction'] == 'QLD') & (df['Year'] == '2021-22')]
        df_qld_all = df[df['Jurisdiction'] == 'QLD']
        df_all_states = df[(df['Year'] == '2021-22') & (df['Jurisdiction'] != 'AUS')]
        df_qld_all['Year'] = df_qld_all['Year'].apply(lambda x: str(int(x.split('-')[0]) + 1))
        
        # Calculate basic statistics
        stats_dict = {
            'total_records': len(df_qld_focus),
            'years_available': sorted(df['Year'].unique()),
            'states': sorted(df['Jurisdiction'].unique()),
            'sectors': sorted(df_qld_focus['Industry_High_Level'].unique()),
            'fuels': sorted(df_qld_focus[df_qld_focus['Fuel'] != 'Total Net Energy Consumption']['Fuel'].unique())
        }
        
        return df_qld_focus, df_qld_all, df_all_states, electricity_factors, fuel_factors, stats_dict, df, ef_electricity, ef_fuel
        
    except Exception as e:
        st.error(f"Error loading data: {str(e)}")
        return None, None, None, None, None, None

class EmissionsCalculator:
    def __init__(self, df, electricity_factors, fuel_factors):
        self.df = df
        self.ef_electricity = electricity_factors
        self.ef_fuel = fuel_factors
        self.renewable_sources = ['Solar energy', 'Bagasse', 'Wood, woodwaste', 'Liquid/Gas biofuels']
    
    def calculate_emissions(self):
        """Calculate comprehensive emissions with statistical analysis"""
        results = {
            'scope1': {'total': 0, 'by_fuel': {}, 'by_sector': {}, 'by_industry': {}},
            'scope2': {'total': 0, 'by_sector': {}, 'by_industry': {}},
            'renewable': {'total': 0, 'by_source': {}, 'by_sector': {}},
            'intensity': {'by_sector': {}},
            'statistics': {}
        }
        
        # Calculate emissions for each sector
        for sector in self.df['Industry_High_Level'].unique():
            if pd.isna(sector):
                continue
            
            sector_data = self.df[self.df['Industry_High_Level'] == sector]
            
            # Calculate Scope 1 emissions
            scope1 = self._calculate_scope1(sector_data)
            results['scope1']['by_sector'][sector] = scope1
            
            # Calculate Scope 2 emissions
            scope2 = self._calculate_scope2(sector_data)
            results['scope2']['by_sector'][sector] = scope2
            
            # Calculate renewable energy
            renewable = self._calculate_renewable(sector_data)
            results['renewable']['by_sector'][sector] = renewable
            
            # Calculate intensity
            total_energy = sector_data[
                (sector_data['Fuel'] != 'Total Net Energy Consumption') & 
                (sector_data['EnergyContext'] == 'Consumption')
            ]['Quantity'].sum()
            
            if total_energy > 0:
                results['intensity']['by_sector'][sector] = (scope1 + scope2) / total_energy
        
        # Calculate totals and statistics
        results['scope1']['total'] = sum(results['scope1']['by_sector'].values())
        results['scope2']['total'] = sum(results['scope2']['by_sector'].values())
        results['renewable']['total'] = sum(results['renewable']['by_sector'].values())
        
        # Calculate statistical measures
        intensities = list(results['intensity']['by_sector'].values())
        results['statistics'] = {
            'intensity_mean': np.mean(intensities),
            'intensity_std': np.std(intensities),
            'intensity_median': np.median(intensities),
            'intensity_skew': stats.skew(intensities),
            'intensity_kurtosis': stats.kurtosis(intensities)
        }
        
        return results
    
    def _calculate_scope1(self, data):
        """Calculate Scope 1 emissions with detailed fuel breakdown"""
        emissions = 0
        fuel_emissions = {}
        
        for fuel, factors in self.ef_fuel.items():
            if fuel not in self.renewable_sources:
                fuel_data = data[data['Fuel'] == fuel]
                if not fuel_data.empty and fuel_data['Quantity'].sum() > 0:
                    quantity_pj = fuel_data['Quantity'].sum()
                    fuel_emission = quantity_pj * factors['EF_tCO2e_PJ'] / 1_000_000
                    emissions += fuel_emission
                    fuel_emissions[fuel] = fuel_emission
        
        return emissions
    
    def _calculate_scope2(self, data):
        """Calculate Scope 2 emissions from electricity consumption"""
        electricity_data = data[data['Fuel'] == 'Electricity']
        if not electricity_data.empty:
            quantity_pj = electricity_data['Quantity'].sum()
            return quantity_pj * self.ef_electricity['EF_tCO2e_PJ'] / 1_000_000
        return 0
    
    def _calculate_renewable(self, data):
        """Calculate renewable energy contribution"""
        renewable = 0
        for source in self.renewable_sources:
            source_data = data[data['Fuel'] == source]
            if not source_data.empty:
                renewable += source_data['Quantity'].sum()
        return renewable

class StatisticalAnalysis:
    @staticmethod
    def perform_analysis(df, results):
        """Perform comprehensive statistical analysis"""
        stats = {}
        
        # Emission distribution statistics
        emissions = pd.Series(results['scope1']['by_sector'])
        stats['emissions'] = {
            'mean': emissions.mean(),
            'median': emissions.median(),
            'std': emissions.std(),
            'skew': emissions.skew(),
            'kurtosis': emissions.kurtosis()
        }
        
        # Sector correlation analysis
        sector_data = pd.DataFrame({
            'scope1': pd.Series(results['scope1']['by_sector']),
            'scope2': pd.Series(results['scope2']['by_sector']),
            'intensity': pd.Series(results['intensity']['by_sector'])
        })
        stats['correlations'] = sector_data.corr()
        
        return stats


class EnhancedVisualizations:
    @staticmethod
    def create_overview_dashboard(results, stats):
        st.header("Queensland Emissions Overview")
        
        # Calculate target comparisons
        scope1_target = 93  # Mt CO2e
        scope2_target = 47.5
        total_target = scope1_target + scope2_target # Using midpoint of Scope 2 target (45-50)
        
        scope1_actual = results['scope1']['total']
        scope2_actual = results['scope2']['total']
        total_actual = scope1_actual + results['scope2']['total']
        
        # Calculate percentage differences
        scope1_diff_pct = ((scope1_actual - scope1_target) / scope1_target) * 100
        scope2_diff_pct = ((scope2_actual - scope2_target) / scope2_target) * 100
        total_diff_pct = ((total_actual - total_target) / total_target) * 100
        
        # Create metrics
        col1, col5, col2, col3, col4 = st.columns(5)
        
        with col1:
            st.metric(
                "Scope 1 Emissions",
                f"{scope1_actual:.2f} Mt CO2e",
                f"{scope1_diff_pct:+.1f}% from target",
                delta_color="inverse"  # Red if above target, green if below
            )
        with col5:
            st.metric(
                "Scope 2 Emissions",
                f"{scope2_actual:.2f} Mt CO2e",
                f"{scope2_diff_pct:+.1f}% from target",
                delta_color="inverse"  # Red if above target, green if below
            )
        with col2:
            st.metric(
                "Total Emissions",
                f"{total_actual:.2f} Mt CO2e",
                f"{total_diff_pct:+.1f}% from target",
                delta_color="inverse"
            )
        
        with col3:
            # Calculate renewable contribution to emissions reduction
            renewable_offset = results['renewable']['total'] * (scope1_actual / sum(results['scope1']['by_sector'].values()))
            st.metric(
                "Renewable Contribution",
                f"{results['renewable']['total']:.1f} PJ",
                f"Offsetting {renewable_offset:.2f} Mt CO2e"
            )
        
        with col4:
            # Calculate emission intensity relative to target
            target_intensity = scope1_target / sum(results['scope1']['by_sector'].values())
            actual_intensity = stats['emissions']['mean']
            intensity_diff_pct = ((actual_intensity - target_intensity) / target_intensity) * 100
            
            st.metric(
                "Emission Intensity",
                f"{actual_intensity:.3f} Mt CO2e/PJ",
                f"{intensity_diff_pct:+.1f}% from target intensity",
                delta_color="inverse"
            )

    @staticmethod
    def create_sector_comparison(df_qld_focus, df_all_states, results):
        st.subheader("Sector Analysis")
        
        tab1, tab2, tab3 = st.tabs(["State Comparison", "Sector Breakdown", "Intensity Analysis"])
        
        with tab1:
            # Create enhanced heatmap
            energy_by_state_sector = pd.pivot_table(
                df_all_states,
                values='Quantity',
                index='Jurisdiction',
                columns='Industry_High_Level',
                aggfunc='sum'
            )
            
            fig = go.Figure(data=go.Heatmap(
                z=energy_by_state_sector.values,
                x=energy_by_state_sector.columns,
                y=energy_by_state_sector.index,
                colorscale='RdBu_r',
                customdata=np.dstack((energy_by_state_sector.values,)),
                hovertemplate='State: %{y}<br>Sector: %{x}<br>Energy: %{customdata[0]:.1f} PJ<extra></extra>'
            ))
            
            fig.update_layout(
                title='Energy Consumption by State and Sector',
                height=600
            )
            
            st.plotly_chart(fig, use_container_width=True)
        
        with tab2:
            # Create sector emissions breakdown
            sector_data = pd.DataFrame({
                'Sector': list(results['scope1']['by_sector'].keys()),
                'Scope 1': list(results['scope1']['by_sector'].values()),
                'Scope 2': [results['scope2']['by_sector'].get(sector, 0) 
                           for sector in results['scope1']['by_sector'].keys()],
                'Total': [results['scope1']['by_sector'][sector] + 
                         results['scope2']['by_sector'].get(sector, 0)
                         for sector in results['scope1']['by_sector'].keys()]
            }).sort_values('Total', ascending=True)

            # Create stacked bar chart
            fig = go.Figure()
            fig.add_trace(go.Bar(
                name='Scope 1',
                x=sector_data['Scope 1'],
                y=sector_data['Sector'],
                orientation='h',
                marker_color='rgb(55, 83, 109)'
            ))
            fig.add_trace(go.Bar(
                name='Scope 2',
                x=sector_data['Scope 2'],
                y=sector_data['Sector'],
                orientation='h',
                marker_color='rgb(26, 118, 255)'
            ))

            fig.update_layout(
                title='Emissions by Sector',
                barmode='stack',
                yaxis={'categoryorder': 'total ascending'},
                xaxis_title='Emissions (Mt CO2e)',
                height=600
            )
            st.plotly_chart(fig, use_container_width=True)

            # Create treemap in separate chart
            fig_treemap = go.Figure(go.Treemap(
                labels=[f"{sector} ({value:.1f} Mt)" for sector, value in 
                       zip(sector_data['Sector'], sector_data['Total'])],
                parents=[''] * len(sector_data),
                values=sector_data['Total'],
                textinfo="label+percent parent"
            ))
            fig_treemap.update_layout(
                title='Sector Contribution to Total Emissions',
                height=500
            )
            st.plotly_chart(fig_treemap, use_container_width=True)
        
        with tab3:
            # Calculate and display intensity metrics
            intensity_data = pd.DataFrame({
                'Sector': list(results['intensity']['by_sector'].keys()),
                'Intensity': list(results['intensity']['by_sector'].values())
            }).sort_values('Intensity', ascending=False)

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=intensity_data['Sector'],
                y=intensity_data['Intensity'],
                marker_color='rgb(55, 83, 109)'
            ))

            # Add average line
            avg_intensity = intensity_data['Intensity'].mean()
            fig.add_hline(
                y=avg_intensity,
                line_dash="dash",
                annotation_text=f"Average: {avg_intensity:.2f}"
            )

            fig.update_layout(
                title='Emission Intensity by Sector',
                xaxis_title='Sector',
                yaxis_title='Intensity (Mt CO2e/PJ)',
                height=500
            )
            
            st.plotly_chart(fig, use_container_width=True)

            # Add statistical insights
            col1, col2 = st.columns(2)
            with col1:
                st.write("**Intensity Statistics**")
                st.write(f"- Mean: {intensity_data['Intensity'].mean():.3f} Mt CO2e/PJ")
                st.write(f"- Median: {intensity_data['Intensity'].median():.3f} Mt CO2e/PJ")
                st.write(f"- Std Dev: {intensity_data['Intensity'].std():.3f} Mt CO2e/PJ")
            
            with col2:
                st.write("**Key Findings**")
                st.write(f"- Most Intensive: {intensity_data['Sector'].iloc[0]}")
                st.write(f"- Least Intensive: {intensity_data['Sector'].iloc[-1]}")
                st.write(f"- Sectors above average: {sum(intensity_data['Intensity'] > avg_intensity)}")



    @staticmethod
    def create_fuel_sector_sunburst(df_qld_focus):
        """Create enhanced sunburst visualization with data validation"""
        try:
            # Filter and prepare data
            df_sunburst = df_qld_focus[
                (df_qld_focus['Fuel'] != 'Total Net Energy Consumption') &
                (df_qld_focus['Quantity'] > 0)  # Filter out zero quantities
            ].copy()
            
            # Add rounded energy values
            df_sunburst['Energy (PJ)'] = df_sunburst['Quantity'].round(2)
            
            # Create hierarchical structure
            df_sunburst['All'] = 'Total Energy Consumption'
            
            # Create enhanced sunburst
            fig = go.Figure(go.Sunburst(
                ids=df_sunburst['Fuel'],
                labels=df_sunburst['Fuel'],
                parents=df_sunburst['Industry_High_Level'],
                values=df_sunburst['Energy (PJ)'],
                branchvalues='total',
                hovertemplate="""
                <b>Sector</b>: %{parent}<br>
                <b>Fuel</b>: %{label}<br>
                <b>Energy</b>: %{value:.1f} PJ<br>
                <extra></extra>
                """,
                maxdepth=2
            ))
            
            fig.update_layout(
                title={
                    'text': 'Energy Consumption by Sector and Fuel Type',
                    'x': 0.5,
                    'y': 0.95,
                    'xanchor': 'center',
                    'yanchor': 'top'
                },
                width=600,
                height=600
            )
            
            return fig
        
        except Exception as e:
            st.error(f"Error creating sunburst plot: {str(e)}")
            st.write("Debugging information:")
            st.write(df_qld_focus['Industry_High_Level'].value_counts())
            st.write(df_qld_focus['Fuel'].value_counts())
            return None

    @staticmethod
    def create_detailed_analysis(df_qld_all, df_qld_focus, results):
        
        # Time series analysis
        st.write("### Historical Trend of Queensland's Energy Consumption")
        
        # Convert Year to proper format for plotting
        time_series = df_qld_all.groupby(['Year', 'Industry_High_Level'])['Quantity'].sum().reset_index()
        
        fig = px.line(
            time_series,
            x='Year',
            y='Quantity',
            color='Industry_High_Level',
            title='Energy Consumption Trends',
            markers=True,
            line_shape='linear'
        )
        
        fig.update_layout(
            xaxis_title="Year",
            yaxis_title="Energy Consumption (PJ)",
            height=600,
            showlegend=True,
            legend_title="Industry Sector",
            shapes=[
                dict(
                    type="rect",
                    xref="x",
                    yref="paper",
                    x0="2021-22",
                    x1="2021-22",
                    y0=0,
                    y1=1,
                    fillcolor="rgba(255,0,0,0.1)",
                    line_width=0,
                    layer="below"
                )
            ],
            annotations=[
                dict(
                    x="2021-22",
                    y=1.05,
                    xref="x",
                    yref="paper",
                    text="",
                    showarrow=False,
                    font=dict(color="red")
                )
            ]
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Create fuel mix analysis
        st.write("### Fuel Mix Analysis")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Fuel mix donut chart
            fuel_mix = df_qld_focus[
                df_qld_focus['Fuel'] != 'Total Net Energy Consumption'
            ].groupby('Fuel')['Quantity'].sum().sort_values(ascending=True)
            
            fig = go.Figure(data=[go.Pie(
                labels=fuel_mix.index,
                values=fuel_mix.values,
                hole=.4,
                textinfo='label+percent',
                textposition='inside',
                insidetextorientation='radial'
            )])
            
            fig.update_layout(
                title='Fuel Mix Distribution',
                annotations=[dict(text='Fuel Types', x=0.5, y=0.5, font_size=20, showarrow=False)],
                height=500
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Create and display enhanced sunburst
            try:
                sunburst_fig = EnhancedVisualizations.create_fuel_sector_sunburst(df_qld_all)
                st.plotly_chart(sunburst_fig, use_container_width=True)
            except Exception as e:
                st.error(f"Error creating sunburst plot: {str(e)}")
                st.write("Debugging information:")
                st.write(df_qld_all['Industry_High_Level'].value_counts())
                st.write(df_qld_all['Fuel'].value_counts())
        
        # Add summary statistics
        st.write("### Summary Statistics for Queensland in 2022")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(
                "Total Energy Consumption",
                f"{df_qld_focus['Quantity'].sum():.1f} PJ",
                "All sectors"
            )
        
        with col2:
            st.metric(
                "Number of Fuel Types",
                len(fuel_mix),
                "Excluding total consumption"
            )
        
        with col3:
        # Get the top 5 consuming sectors
            top_sectors = fuel_mix.nlargest(5)
            
            # Create a DataFrame for the top 5 sectors
            top_sectors_df = pd.DataFrame({
                'Sector': top_sectors.index,
                'Consumption (PJ)': top_sectors.values
            })
            
            # Display the top 5 sectors in a table
            st.write("Top 5 Consuming Sectors")
            st.table(top_sectors_df)

def main():
    st.title("Queensland Energy & Emissions Analysis Dashboard")
    
    # Load data
    df_qld_focus, df_qld_all, df_all_states, electricity_factors, fuel_factors, stats_dict, df, ef_electricity, ef_fuel = load_data()
    
    if df_qld_focus is None:
        st.error("Failed to load data. Please check your data files.")
        return
    
    # Add data info to sidebar
    with st.sidebar:
        st.header("Data Information")
        st.write(f"Focus Year: 2021-22")
        st.write(f"Total Records: {stats_dict['total_records']:,}")
        st.write(f"Number of Sectors: {len(stats_dict['sectors'])}")
        excel_data = create_excel_download(df, ef_electricity, ef_fuel)
        st.download_button(
            label="📥 Export Complete Dataset",
            data=excel_data,
            file_name="qld_energy_emissions_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        # Add methodology documentation
        with st.expander("📚 Methodology"):
            st.markdown("""
            ### Emissions Calculations
            
            **Scope 1 Emissions**
            ```
            Emissions = Activity Data (PJ) × Emission Factor (t CO2e/PJ) / 1,000,000
            ```
            
            **Scope 2 Emissions**
            ```
            Emissions = Electricity (PJ) × Grid Factor (t CO2e/PJ) / 1,000,000
            ```
            
            **Emission Intensity**
            ```
            Intensity = (Scope 1 + Scope 2) / Total Energy
            ```
            """)
    
    # Calculate emissions
    calculator = EmissionsCalculator(df_qld_focus, electricity_factors, fuel_factors)
    results = calculator.calculate_emissions()
    
    # Perform statistical analysis
    stats = StatisticalAnalysis.perform_analysis(df_qld_focus, results)
    
    # Create visualizations
    EnhancedVisualizations.create_overview_dashboard(results, stats)
    EnhancedVisualizations.create_sector_comparison(df_qld_focus, df_all_states, results)
    EnhancedVisualizations.create_detailed_analysis(df_qld_all,df_qld_focus, results)
    
    # Display insights
    #display_insights(results, df_qld_focus)

if __name__ == "__main__":
    main()